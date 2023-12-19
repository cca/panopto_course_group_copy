# Panopto Course Group Copy

When we delete a course in Moodle, we lose the Panopto groups associated with it. This script will copy the Panopto course group to a new, internal group with the same membership to ensure faculty and students retain access to videos in their course folders after course deletion. See [my forum post](https://community.panopto.com/discussion/2203/copying-lms-groups-to-internal-ones#latest) for some details and advice from Panopto support. While the script could easily be adapted for other use cases, right now it is tightly coupled to this particular one. For instance, the script assumes that the root folder is a semester, the course folders are the root's grandchildren, and it does not copy Publisher groups because we don't use them.

It looks like we can use these API calls:

- Pass the root group folder ID (which will be a semester, e.g. Moodle > 2020FA)
- SessionManagement [GetFoldersById](https://support.panopto.com/resource/APIDocumentation/Help/html/8b717611-47d1-8b7e-9b0e-58b82b838ddc.htm)
- Call GetFoldersById with the child folder IDs to get their grandchild folders (which will be courses, e.g. Moodle > 2020FA > ANIMA > Animation 101)
- AccessManagement [GetFolderAccessDetails](https://support.panopto.com/resource/APIDocumentation/Help/html/49e70152-141e-cb7f-0bda-ba1277b91d63.htm) to get a list of groups on the course folder
- UserManagement [GetGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/3aa4f0ce-0b57-3e66-7bf8-35bf12bc0f93.htm) to determine whether the group is internal or not
- UserManagement [GetUsersInGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/52df0610-2118-d043-21c9-afbdef292125.htm) to get the members of the group
- UserManagement [CreateInternalGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/40b226f3-98ab-3c32-1810-49af5e4e3d45.htm) to create a new internal group
- **QUESTION** can we initialize the new internal group with members or do we need UM [AddMembersToInternalGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/a1043b37-497e-b3e6-9f30-0f98cdc40a33.htm), too?
- AccessManagement [GrantGroupAccessToFolder](https://support.panopto.com/resource/APIDocumentation/Help/html/83a83ca4-af47-d860-e477-8a1f36dfc86b.htm) to give the new internal group access to the course folder

## Setup

```sh
pipenv install
cp example.env .env
$EDITOR .env # fill in values
```

## Usage

Find ID of the _semester_ folder in Panopto (browse to the folder and look at the **Manage** tab in the web UI). Then run:

```sh
# you can also specify ROOT_FOLDER in .env
pipenv run python app.py ROOT_FOLDER_ID
```

This iterates over all the grandchild course folders and copies their creator and access groups to internal groups.

## LICENSE

[ECL Version 2.0](https://opensource.org/licenses/ECL-2.0)
