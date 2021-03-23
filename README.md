# Gitlab2Github

A simple script to migrate a Git repository from Gitlab to Github.
It requires Python version > 3.8 because of the asyncio usage.

### Features

This script can migrate the following entries:

1. Labels
2. Milestones
3. Issues (and the main comments)
4. Merge requests (and the main comments)

It also supports a user-mapping list to change the citations from Gitlab users to 
Github users.

### Usage

1. First, import your Gitlab repository into Github using the official tool.

https://github.com/new/import

2. Create your `config.ini` using the `config.ini.example` as an example.

3. Create a virtualenv and install the required libraires. For example:

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

4. Finally, run the script.

```bash
python3 gitlab2github.py
```

### Limitations

This script covers the migration of basic content only. Issues and merge requests may have
a lot of details (code comments, attachements, etc).

One critical limitation of this script is that it creates all content as a single user.
That means all issues, comments, etc will be owned by the running user.

If you want to explore more both APIs:

https://docs.gitlab.com/ee/api/

https://docs.github.com/en/rest/reference