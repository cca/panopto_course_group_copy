# Panopto Course Group Copy

When we delete a course in Moodle, we lose the Panopto groups associated with it. This script copies the Panopto course group to a new, internal group with the same membership to ensure faculty and students retain access to videos in their course folders after course deletion. See [my forum post](https://community.panopto.com/discussion/2203/copying-lms-groups-to-internal-ones#latest) for some details and advice from Panopto support. While the script could easily be adapted for other use cases, right now it is tightly coupled to this particular one. For instance, the script assumes:

- the root folder is a semester
- the course folders are the root's grandchildren
- Publisher groups aren't needed (thus not copied) because we don't use them

## Setup

```sh
pipenv install
cp example.env .env
$EDITOR .env # fill in values
```

The `APP_KEY` env var is the Application Key of the [Identity Provider](https://ccarts.hosted.panopto.com/Panopto/Pages/Admin/Providers.aspx) (IDP) we're using.

## Usage

Find ID of the _semester_ folder in Panopto (browse to the folder and look at the **Manage** tab in the web UI). Then run:

```sh
# you can also specify ROOT_FOLDER in .env
pipenv run python app.py ROOT_FOLDER_ID
```

This iterates over all the grandchild course folders and copies their creator and access groups to internal groups. The `LOGLEVEL` config/env var can be set to `DEBUG` to see the objects returned by the Panopto SOAP API.

## Panopto SOAP API Details

There are some nuances to using the Panopto SOAP APIs. When looking at [their public documentation](https://support.panopto.com/resource/APIDocumentation/Help/html/420f7b22-2670-6e25-1a92-84f84fad0d49.htm), only the methods on the `I... Interface` objects can be called. Other objects are structural information. Each interface requires a separate SOAP client; this script uses three clients.

Authentication would look different if we were using internal Panopto accounts (not external IDPs) with a password; it's easy to find out how in the Panopto SOAP examples. In general, when using an external account source like Moodle or our SSO, you must prefix the username with the IDP like `sso.cca.edu\\ephetteplace` (two backslashes because it's the Python escape character).

Where a method accepts a list of IDs, like `GetFoldersById`, we can pass either a single-entry list or a guid dict like `{ "guid": [id1, id2, ...]}`. If you pass a multi-entry list like `GetFoldersById(auth=AuthInfo, folderIds=[id1, id2])`, Panopto will happily return results for only `id1` with no warning.

Methods return either a list of objects or `None` (_not_ an empty list). So we cannot `for user in GetUsersInGroup(): do_something(user)` because if there are no users in a group, it's a TypeError.

This is the chain of API calls the script makes:

- SessionManagement [GetFoldersById](https://support.panopto.com/resource/APIDocumentation/Help/html/8b717611-47d1-8b7e-9b0e-58b82b838ddc.htm)
- Call `GetFoldersById` again with the child folder IDs to get grandchild folders (which are course folders, e.g. Moodle > 2020FA > ANIMA > Animation 101)
- AccessManagement [GetFolderAccessDetails](https://support.panopto.com/resource/APIDocumentation/Help/html/49e70152-141e-cb7f-0bda-ba1277b91d63.htm) to get a list of groups on the course folder
- UserManagement [GetGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/3aa4f0ce-0b57-3e66-7bf8-35bf12bc0f93.htm) to determine whether groups are external or not
- UserManagement [GetUsersInGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/52df0610-2118-d043-21c9-afbdef292125.htm) to get the members of the groups
- UserManagement [CreateInternalGroup](https://support.panopto.com/resource/APIDocumentation/Help/html/40b226f3-98ab-3c32-1810-49af5e4e3d45.htm) to create new internal groups
- AccessManagement [GrantGroupAccessToFolder](https://support.panopto.com/resource/APIDocumentation/Help/html/83a83ca4-af47-d860-e477-8a1f36dfc86b.htm) to give the new internal groups access to the course folders

## LICENSE

[ECL Version 2.0](https://opensource.org/licenses/ECL-2.0)
