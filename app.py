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
if len(sys.argv) > 1:
    config["ROOT_FOLDER"] = sys.argv[1]


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

root_folder = SessionManagement.service.GetFoldersById(
    auth=AuthenticationInfo,
    folderIds=[config["ROOT_FOLDER"]],
)[0]
logger.info(
    f"Got root folder {root_folder['Name']}, number of children: {len(root_folder['ChildFolders']['guid'])}"
)
logger.debug(root_folder)


def create_group(group):
    # note: cannot create two internal groups with the same name
    # which will be a good sanity check for this script
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
            # roles are strings: Creator, Viewer, ViewerWithLink, Publisher
            AccessManagement.service.GrantGroupAccessToFolder(
                auth=AuthenticationInfo,
                folderId=folder_id,
                groupId=internal_group["Id"],
                role=role,
            )
            logger.info(f"Added group {group['Name']} to course folder")


def copy_folder_groups(folder_id):
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


for folder_id in root_folder["ChildFolders"]["guid"]:
    # GetFoldersById takes a list of folder IDs but seems to just error out if you
    # ask for too many (>53?) instead of paging, great job Panopto
    # departmental folders, none of these will have groups
    department_folder = SessionManagement.service.GetFoldersById(
        auth=AuthenticationInfo, folderIds=[folder_id]
    )[0]
    logger.info(f"Got department folder {department_folder['Name']}")
    logger.debug(department_folder)
    if department_folder["ChildFolders"]:
        # ! probably has the same problem as above
        course_folders = SessionManagement.service.GetFoldersById(
            auth=AuthenticationInfo,
            folderIds={"guid": department_folder["ChildFolders"]["guid"]},
        )
        logger.info(
            f"Got {len(course_folders)} children of {department_folder['Name']}"
        )
        for course_folder in course_folders:
            copy_folder_groups(course_folder["Id"])
