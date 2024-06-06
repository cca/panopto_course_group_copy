import argparse
from datetime import date
import hashlib
import logging
import os
import re

from dotenv import dotenv_values
from zeep import Client  # other SOAP clients like pysimplesoap have not worked
from zeep.exceptions import Fault

# stop the annoying "Forcing soap:address location to HTTPS" from zeep logs
logging.getLogger("zeep").setLevel(logging.ERROR)

config = {
    **dotenv_values(".env"),
    **os.environ,  # override loaded values with environment variables
}

# initialize a logger, use config LOGLEVEL if set, otherwise INFO
logger = logging.getLogger(__name__)
logger.setLevel(config.get("LOGLEVEL", "INFO"))
# log to stdout
handler = logging.StreamHandler()
logger.addHandler(handler)
# and to file dated today
handler = logging.FileHandler(f"{date.today().isoformat()}.log")
logger.addHandler(handler)


# based on code from Panopto SOAP examples
def generateauthcode(userkey, servername, sharedSecret):
    payload = userkey + "@" + servername
    signedPayload = payload + "|" + sharedSecret
    m = hashlib.sha1()
    m.update(signedPayload.encode("utf-8"))
    authcode = m.hexdigest().upper()
    return authcode


def add_group_to_folder(group, folder_id, role):
    # add internal group to course folder
    if args.dry_run:
        return logger.info(
            f"Would add group {group['Name']} to course folder with role {role}"
        )

    AccessManagement.service.GrantGroupAccessToFolder(
        auth=AuthenticationInfo,
        folderId=folder_id,
        groupId=group["Id"],
        # roles are strings: Creator, Viewer, ViewerWithLink, Publisher
        role=role,
    )
    logger.info(f"Gave group {group['Name']} {role} access to course folder")


def create_group(group, folder_id=""):
    # ! Cannot create two internal groups with the same name, good sanity check
    # ! append a short hash of group & folder UUID to make them unique per folder
    # https://github.com/cca/panopto_course_group_copy/issues/3
    hash = hashlib.sha1(f"{group['Name']}{folder_id}".encode()).hexdigest()[:6]
    name = f"{group['Name']} (internal {hash})"

    if args.dry_run:
        logger.info(f"Would create group {name} with members {group['MemberIds']}")
        return group

    try:
        group = UserManagement.service.CreateInternalGroup(
            auth=AuthenticationInfo,
            groupName=name,
            memberIds={"guid": group["MemberIds"]},
        )
    except Fault as e:
        # rest of the exception properties are not useful
        logger.error(
            f"Error creating group {group['Name']} on folder {folder_id}:\n{e.message}"
        )
        return None

    logger.info(f"Created group {name}")
    logger.debug(group)
    return group


def copy_group(group_id, folder_id, role):
    # this does not have the group members but has other data
    group = UserManagement.service.GetGroup(auth=AuthenticationInfo, groupId=group_id)
    logger.info(f"Got group {group['Name']}")
    logger.debug(group)
    # Only copy course folder groups
    provider = config.get("PROVIDER", True)
    if (
        group["GroupType"] == "External"
        and (group["MembershipProviderName"] == provider or provider)
        and (args.filter is None or args.filter.search(group["Name"]))
    ):
        # get group members, this is either None or actual list not {"guid": []}
        group_members = UserManagement.service.GetUsersInGroup(
            auth=AuthenticationInfo, groupId=group_id
        )
        if group_members:
            logger.info(f"Got {len(group_members)} members of {group['Name']}")
            logger.debug(group_members)
            internal_group = create_group(
                {
                    "Name": group["Name"],
                    "MemberIds": group_members,
                },
                folder_id,
            )

            if internal_group:
                add_group_to_folder(internal_group, folder_id, role)


def course_folder(folder_id):
    ad = AccessManagement.service.GetFolderAccessDetails(
        auth=AuthenticationInfo, folderId=folder_id
    )
    logger.info(f"Got access details for course folder")
    logger.debug(ad)

    # sometimes Creator group also has Viewer access which is redundant
    # and causes an error when trying to add the group to the folder
    # here we remove any Creator group from the Viewer list
    viewer_groups = (
        set(ad["GroupsWithViewerAccess"]["guid"])
        if ad["GroupsWithViewerAccess"]
        else set()
    )
    creator_groups = (
        set(ad["GroupsWithCreatorAccess"]["guid"])
        if ad["GroupsWithCreatorAccess"]
        else set()
    )
    viewer_groups = viewer_groups - creator_groups

    for group_id in creator_groups:
        copy_group(group_id, folder_id, "Creator")

    for group_id in viewer_groups:
        copy_group(group_id, folder_id, "Viewer")


def dept_folder(folder_id):
    # GetFoldersById takes a list of folder IDs so you would think we could
    # pass a list of ids to process all departments at once but the method
    # errors if you ask for too many (>53?), great job Panopto
    folder = SessionManagement.service.GetFoldersById(
        auth=AuthenticationInfo, folderIds=[folder_id]
    )[0]
    logger.info(f"Got department folder {folder['Name']}")
    logger.debug(folder)
    if folder["ChildFolders"]:
        logger.info(f"Number of children: {len(folder['ChildFolders']['guid'])}")
        # ! As with above, requesting too many folders at once causes an error in Zeep
        # ! https://github.com/cca/panopto_course_group_copy/issues/4
        for child_guid in folder["ChildFolders"]["guid"]:
            child = SessionManagement.service.GetFoldersById(
                auth=AuthenticationInfo,
                folderIds=[child_guid],
            )[0]
            logger.info(f"Got {child['Name']} child of {folder['Name']}")
            course_folder(child["Id"])


def term_folder(folder_id):
    folder = SessionManagement.service.GetFoldersById(
        auth=AuthenticationInfo,
        folderIds=[folder_id],
    )[0]
    logger.info(
        f"Got term folder {folder['Name']}, number of children: {len(folder['ChildFolders']['guid'])}"
    )
    logger.debug(folder)
    for folder_id in folder["ChildFolders"]["guid"]:
        dept_folder(folder_id)


def main(args):
    # execute starting at whatever level was specified
    globals()[f"{args.folder_type}_folder"](args.folder_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Copy Moodle course user groups to internal ones. If given a term or department folder, this will traverse the folder hierarchy and copy all groups in descendent course folders."
    )
    # work at three levels: term ("2021SP"), department ("ANIMA"), course ("ANIMA-101-01")
    parser.add_argument(
        "folder_type",
        choices=["term", "dept", "course"],
        default="term",
        help="starting folder type (defaults to term)",
        nargs="?",
    )
    parser.add_argument(
        "folder_id",
        type=str,
        default=config["FOLDER"],
        help="folder ID (defaults to FOLDER in .env)",
        nargs="?",
    )
    parser.add_argument(
        "--filter",
        type=re.compile,
        help="regex filter for group names to include (e.g. for the semester parenthetical)",
        nargs="?",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="do not create groups"
    )

    global args
    args = parser.parse_args()

    if args.dry_run:
        logger.warning("Dry run, no groups will be created")

    # if we got this far, there wasn't a --help flag, initialize SOAP clients
    global AccessManagement, SessionManagement, UserManagement, AuthenticationInfo
    # initialize SOAP clients
    AccessManagement = Client(
        f'https://{config["HOST"]}/Panopto/PublicAPI/4.6/AccessManagement.svc?wsdl'
    )
    SessionManagement = Client(
        f'https://{config["HOST"]}/Panopto/PublicAPI/4.6/SessionManagement.svc?wsdl'
    )
    UserManagement = Client(
        f'https://{config["HOST"]}/Panopto/PublicAPI/4.6/UserManagement.svc?wsdl'
    )

    # generate authcode and add to AuthenticationInfo object
    authcode = generateauthcode(
        f"{config['IDP']}\\{config['USERNAME']}", config["HOST"], config["APP_KEY"]
    )
    AuthenticationInfo = {
        "AuthCode": authcode,
        "UserKey": f"{config['IDP']}\\{config['USERNAME']}",
    }
    main(args)
