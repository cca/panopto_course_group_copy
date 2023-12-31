import argparse
import hashlib
import logging
import os
import sys

from dotenv import dotenv_values
from zeep import Client  # other SOAP clients like pysimplesoap have not worked

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


# based on code from Panopto SOAP examples
def generateauthcode(userkey, servername, sharedSecret):
    payload = userkey + "@" + servername
    signedPayload = payload + "|" + sharedSecret
    m = hashlib.sha1()
    m.update(signedPayload.encode("utf-8"))
    authcode = m.hexdigest().upper()
    return authcode


# TODO doing all this initialization here makes running just the argparse
# TODO --help take a long time, maybe move it into main()?
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


def create_group(group):
    # note: cannot create two internal groups with the same name
    # which will be a good sanity check for this script
    if args.dry_run:
        logger.info(
            f"Would create group {group['Name']} with members {group['MemberIds']}"
        )
        return group
    group = UserManagement.service.CreateInternalGroup(
        auth=AuthenticationInfo,
        groupName=group["Name"],
        memberIds={"guid": group["MemberIds"]},
    )
    logger.info(f"Created group {group['Name']}")
    logger.debug(group)
    return group


def copy_group(group_id, folder_id, role):
    # this does not have the group members but has other data
    group = UserManagement.service.GetGroup(auth=AuthenticationInfo, groupId=group_id)
    logger.info(f"Got group {group['Name']}")
    logger.debug(group)
    # For course folder groups from Moodle
    # MembershipProviderName = moodle-production & GroupType = External
    # TODO provider name should be another config option
    if group["MembershipProviderName"] == "moodle-production":
        # get group members, this is eitehr None or actual list not {"guid": []}
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
                }
            )

            # add internal group to course folder
            if args.dry_run:
                logger.info(
                    f"Would add group {group['Name']} to course folder with role {role}"
                )
                return
            AccessManagement.service.GrantGroupAccessToFolder(
                auth=AuthenticationInfo,
                folderId=folder_id,
                groupId=internal_group["Id"],
                # roles are strings: Creator, Viewer, ViewerWithLink, Publisher
                role=role,
            )
            logger.info(f"Added group {group['Name']} to course folder")


def course_folder(folder_id):
    access_details = AccessManagement.service.GetFolderAccessDetails(
        auth=AuthenticationInfo, folderId=folder_id
    )
    logger.info(f"Got access details for course folder")
    logger.debug(access_details)

    if access_details["GroupsWithCreatorAccess"]:
        for group_id in access_details["GroupsWithCreatorAccess"]["guid"]:
            copy_group(group_id, folder_id, "Creator")

    if access_details["GroupsWithViewerAccess"]:
        for group_id in access_details["GroupsWithViewerAccess"]["guid"]:
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
        # ! may run into the same problem as above if there are too many
        child_folders = SessionManagement.service.GetFoldersById(
            auth=AuthenticationInfo,
            folderIds={"guid": folder["ChildFolders"]["guid"]},
        )
        logger.info(f"Got {len(child_folders)} children of {folder['Name']}")
        for child in child_folders:
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
        "-n", "--dry-run", action="store_true", help="do not create groups"
    )
    global args
    args = parser.parse_args()
    if args.dry_run:
        logger.warning("Dry run, no groups will be created")
    main(args)
