#!/usr/bin/env python3

import os
import re
import aiohttp
import asyncio
import logging
import configparser
import urllib.parse

async def main():

  debug = False

  # Define logger formatter and logger object.
  if debug:
    console_formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)20s() | %(message)s")
  else:
    console_formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")

  console_handler = logging.StreamHandler()
  console_handler.setFormatter(console_formatter)
  logger = logging.getLogger()
  logger.addHandler(console_handler)

  if debug:
    logger.setLevel(level=os.environ.get("LOGLEVEL", "DEBUG"))
  else:
    logger.setLevel(level=os.environ.get("LOGLEVEL", "INFO"))

  # Read config file.
  logger.info("Reading config file...")
  cp = configparser.ConfigParser()
  try:
    cp.read("./config.ini")
  except Exception as e:
    logger.error("Couldn't open and/ or parse config file 'config.ini'.")
    if debug:
      logger.debug(repr(e))
    return -1

  # Create gitlab and github config dicts.
  gitlab_config = dict(cp["gitlab"])
  github_config = dict(cp["github"])
  users_mapping = dict(cp["users-mapping"])

  # Prepare tasks to retrieve data from  gitlab.
  logger.info("Creating Gitlab tasks (labels, milestones, issues, and merge requests)...")

  # The order is the same order of the result.
  gitlab_tasks = (
    asyncio.create_task(get_gitlab_issues(logger, debug, gitlab_config)),
    asyncio.create_task(get_gitlab_labels(logger, debug, gitlab_config)),
    asyncio.create_task(get_gitlab_milestones(logger, debug, gitlab_config)),
    asyncio.create_task(get_gitlab_merge_requests(logger, debug, gitlab_config)),
  )

  results = await asyncio.gather(*gitlab_tasks)
  logger.info("Gitlab tasks done.")

  # Any None value here means the request failed.
  gitlab_issues = results[0]
  gitlab_labels = results[1]
  gitlab_milestones = results[2]
  gitlab_merge_requests = results[3]

  # To create Github content, the order matters (some issues may have references to labels or milestones.)
  # Also, if labels or milestones fails, the program should stop (for the same reason).

  # Process labels.
  github_labels_tasks = []
  if gitlab_labels is not None:
    if len(gitlab_labels) > 0:
      logger.info("Creating Github tasks (labels)...")
      for entry in gitlab_labels:
        json = {
          "name": entry["name"],
          "description": entry["description"],
          "color": entry["color"]
        }
        github_labels_tasks.append(asyncio.create_task(github_create_label(logger, debug, github_config, json)))
    else:
      logger.info("There are no labels in this Gitlab project.")
  else:
    logger.info("Failed to retrieve labels from Gitlab.")
    return -2

  results = await asyncio.gather(*github_labels_tasks)
  logger.info("Tasks to create Github labels finished.")

  # Process milestones.
  github_milestones_tasks = []
  if gitlab_milestones is not None:
    if len(gitlab_milestones) > 0:
      logger.info("Creating Github tasks (milestones)...")
      for entry in gitlab_milestones:
        json = {
          "title": entry["title"],
          "description": entry["description"],
          "due_on": entry["due_date"],
          "state": entry["state"],
        }
        github_milestones_tasks.append(asyncio.create_task(github_create_milestone(logger, debug, github_config, json)))
    else:
      logger.info("There are no milestones in this Gitlab project.")
  else:
    logger.info("Failed to retrieve milestones from Gitlab.")
    return -3

  results = await asyncio.gather(*github_milestones_tasks)
  logger.info("Tasks to create Github labels finished.")

  # Process issues.
  github_issues_tasks = []
  if gitlab_issues is not None:
    if len(gitlab_issues) > 0:
      logger.info("Creating Github tasks (issues)...")
      for entry in gitlab_issues:

        username = entry["author"]["username"]
        created_at = entry["created_at"]

        key = username.lower()
        if key in users_mapping.keys():
          username = users_mapping[key]

        body = "Migrated issue created by @{} at {}.\n".format(username, created_at)
        body += 20 * "-" + "\n\n"
        body +=  entry["description"]

        json = {
          "title": entry["title"],
          "body":  body,
          "assignees": entry["assignees"],
          "state": entry["state"],
          # Skipping milestone and labes. For some reason, Gitlab is returning only "opened".
          # "milestone": entry["state"],
          # "labels": entry["state"],
          "notes": entry["notes"],
        }
        github_issues_tasks.append(asyncio.create_task(github_create_issue(logger, debug, github_config, users_mapping, json)))
    else:
      logger.info("There are no issues in this Gitlab project.")
  else:
    logger.info("Failed to retrieve issues from Gitlab.")
    return -3

  results = await asyncio.gather(*github_issues_tasks)
  logger.info("Tasks to create Github issues finished.")

  # Process pull requets.
  github_pull_requests_tasks = []
  if gitlab_merge_requests is not None:
    if len(gitlab_merge_requests) > 0:
      logger.info("Creating Github tasks (pull requests)...")
      for entry in gitlab_merge_requests:
        # Ignore closed merge requests.
        if entry["state"] == "closed":
          continue

        username = entry["author"]["username"]
        created_at = entry["created_at"]

        key = username.lower()
        if key in users_mapping.keys():
          username = users_mapping[key]

        body = "Migrated pull request created by @{} at {}.\n".format(username, created_at)
        body += 20 * "-" + "\n\n"
        body +=  entry["description"]

        json = {
          "title": entry["title"],
          "body": body,
          "head": entry["source_branch"],
          "base": entry["target_branch"],
          "notes": entry["notes"],
        }
        github_pull_requests_tasks.append(asyncio.create_task(github_create_pull_request(logger, debug, github_config, users_mapping, json)))
    else:
      logger.info("There are no merge requests in this Gitlab project.")
  else:
    logger.info("Failed to retrieve merge requests from Gitlab.")
    return -3

  results = await asyncio.gather(*github_pull_requests_tasks)
  logger.info("Tasks to create Github pull requests finished.")

########################################################################################################################
# Gitlab functions.
########################################################################################################################
async def get_gitlab_issues(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/issues".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        content = await response.json()
        # Get notes for each issue.
        for issue in content:
          notes = await get_gitlab_issue_notes(logger, debug, config, issue["iid"])
          issue["notes"] = notes
        return content
    except Exception as e:
      logging.error("Failed to retrive Gitlab issues.")
      if debug:
        logger.debug(str(e))
      return None

async def get_gitlab_issue_notes(logger, debug, config, issue_iid):

  issues_notes_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/issues/{issue_iid}/notes".format(issue_iid=issue_iid, **config))
  headers = {'PRIVATE-TOKEN': config["token"]}

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_notes_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab issues notes.")
      if debug:
        logger.debug(repr(e))
      return None

async def get_gitlab_labels(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/labels".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab labels.")
      if debug:
        logger.debug(repr(e))
      return None

async def get_gitlab_milestones(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/milestones".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}
  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab milestones.")
      if debug:
        logger.debug(repr(e))
      return None

async def get_gitlab_merge_requests(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/merge_requests".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}
  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        content = await response.json()
        # Get notes for each issue.
        for merge_request in content:
          notes = await get_gitlab_merge_requests_notes(logger, debug, config, merge_request["iid"])
          merge_request["notes"] = notes
        return content
    except Exception as e:
      logging.error("Failed to retrive Gitlab merge requests.")
      if debug:
        logger.debug(repr(e))
      return None

async def get_gitlab_merge_requests_notes(logger, debug, config, merge_request_iid):

  merge_request_notes_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/merge_requests/{merge_request_iid}/notes".format(merge_request_iid=merge_request_iid, **config))
  headers = {'PRIVATE-TOKEN': config["token"]}

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(merge_request_notes_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab issues notes.")
      if debug:
        logger.debug(repr(e))
      return None

########################################################################################################################
# Github functions.
########################################################################################################################
async def github_create_label(logger, debug, config, json):

  create_label_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/labels".format(**config))
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:
      # Remove leading '#' (required by Github API: https://docs.github.com/en/rest/reference/issues#create-a-label)
      json["color"] = json["color"].replace("#", "")
      # Create label if it does not exists.

      async with session.post(create_label_url, headers=headers, auth=auth, json=json) as response:
        content = await response.json()
        if "errors" in content.keys():
          logger.error("Error to create label '{name}' (probably already exists).".format(**json))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Label '{name}' created.".format(**json))
    except Exception as e:
      logging.error("Failed to create Github label '{name}'.".format(**json))
      if debug:
        logger.debug(repr(e))

async def github_create_milestone(logger, debug, config, json):

  create_milestone_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/milestones".format(**config))
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:

      # Replace active by open (https://docs.github.com/en/rest/reference/issues#create-a-milestone).
      if json["state"] == "active":
        json["state"] = "open"

      # Remove None due date or convert it to ISO 8601 (YYYY-MM-DDTHH:MM:SSZ).
      if json["due_on"] is None:
        del json["due_on"]
      else:
        json["due_on"] += "T23:59:00Z"

      # Create milestone if it does not exists.
      async with session.post(create_milestone_url, headers=headers, auth=auth, json=json) as response:
        content = await response.json()
        if "errors" in content.keys():
          logger.error("Error to create milestone '{title}' (probably already exists).".format(**json))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Milestone '{title}' created.".format(**json))
    except Exception as e:
      logging.error("Failed to create Github milestone '{title}'.".format(**json))
      if debug:
        logger.debug(repr(e))

async def github_create_issue(logger, debug, config, users_mapping, json):

  create_issue_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/issues".format(**config))
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:

      # Remove None fields (assignee, assignees, labels, etc) (https://docs.github.com/en/rest/reference/issues#create-an-issue).
      for k in list(json.keys()):
        if json[k] == None:
          del json[k]

      # Replace assignee based on user mapping.
      # The assignee is a dict like {'id': , 'name': '', 'username': '', 'state': '', 'avatar_url': ''}
      if "assignees" in json.keys():
        github_assignees = []
        for assignee in json["assignees"]:
          key = assignee["username"].lower()
          if key in users_mapping.keys():
            github_assignees.append(users_mapping[key])
        json["assignees"] = github_assignees

      # Create issue.
      async with session.post(create_issue_url, headers=headers, auth=auth, json=json) as response:
        content = await response.json()

        if "errors" in content.keys():
          logger.error("Error to create issue '{title}' (probably already exists).".format(**json))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Issue '{title}' created.".format(**json))
          # Add issues notes/ comments.
          issue_number = content["number"]
          for note in json["notes"]:

            username = note["author"]["username"]
            created_at = note["created_at"]

            key = username.lower()
            if key in users_mapping.keys():
              username = users_mapping[key]

            body = "Migrated note created by @{} at {}.\n".format(username, created_at)
            body += 20 * "-" + "\n\n"
            body +=  note["body"]

            note_json = {
              "body": body
            }
            await github_create_issue_comment(logger, debug, config, users_mapping, issue_number, note_json)

          # Close issue if its status was closed in Gitlab.
          if json["state"] == "closed":
            await github_close_issue(logger, debug, config, issue_number)

    except Exception as e:
      logging.error("Failed to create Github issue '{title}'.".format(**json))
      if debug:
        logger.debug(repr(e))

async def github_create_issue_comment(logger, debug, config, users_mapping, issue_number, note_json):

  create_issue_comment_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/issues/{issue_number}/comments".format(issue_number=issue_number, **config))
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:
      # Find all possible citations.
      citations = re.findall("@\w+", note_json["body"])

      # Check if the user is in the user-mapping.
      for person in citations:
        key = person[1::].lower()
        if key in users_mapping.keys():
          # Replace username.
          new_username = users_mapping[key]
          note_json["body"] = re.sub(key, new_username, note_json["body"], flags=re.IGNORECASE)

      # Create issue comment.
      async with session.post(create_issue_comment_url, headers=headers, auth=auth, json=note_json) as response:
        content = await response.json()
        if "errors" in content.keys():
          logger.error("Error to create issue comment (probably already exists).".format(**note_json))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Comment for issue #'{issue_number}' created.".format(issue_number=issue_number, **note_json))

    except Exception as e:
      logging.error("Failed to create Github issue comment.")
      if debug:
        logger.debug(repr(e))


async def github_close_issue(logger, debug, config, issue_number):

  close_issue_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/issues/{issue_number}".format(issue_number=issue_number, **config))
  
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:

      # Close issue.
      async with session.post(close_issue_url, headers=headers, auth=auth, json={"state": "closed"}) as response:
        content = await response.json()
        if "errors" in content.keys():
          logger.error("Error to close issue #{issue_number}.".format(issue_number=issue_number))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Issue #'{issue_number}' closed.".format(issue_number=issue_number))

    except Exception as e:
      logging.error("Failed to close Github issue.")
      if debug:
        logger.debug(repr(e))

async def github_create_pull_request(logger, debug, config, users_mapping, json):

  create_pull_request_url = urllib.parse.urljoin(config["url"], "/repos/{owner}/{repo}/pulls".format(**config))
  headers = {
    'Accept': 'application/vnd.github.v3+json'
  }
  auth = aiohttp.BasicAuth(config['user'], config['token'])

  async with aiohttp.ClientSession() as session:
    try:

      # Remove None fields (https://docs.github.com/en/rest/reference/pulls#create-a-pull-request).
      for k in list(json.keys()):
        if json[k] == None:
          del json[k]

      # Create pull request.
      async with session.post(create_pull_request_url, headers=headers, auth=auth, json=json) as response:
        content = await response.json()
        if "errors" in content.keys():
          logger.error("Error to create pull request '{title}' (probably already exists).".format(**json))
          if debug:
            logger.debug(content.get("errors"))
        else:
          logger.info("Pull request '{title}' created.".format(**json))
          # Add pull requests notes/ comments.
          pull_number = content["number"]
          for note in json["notes"]:

            username = note["author"]["username"]
            created_at = note["created_at"]

            key = username.lower()
            if key in users_mapping.keys():
              username = users_mapping[key]

            body = "Migrated note created by @{} at {}.\n".format(username, created_at)
            body += 20 * "-" + "\n\n"
            body +=  note["body"]

            note_json = {
              "body": body,
            }
            # A comment in a merge request webpage is equivalent to a comment in a issue.
            await github_create_issue_comment(logger, debug, config, users_mapping, pull_number, note_json)

    except Exception as e:
      logging.error("Failed to create Github pull request '{title}'.".format(**json))
      if debug:
        logger.debug(repr(e))

if __name__ == "__main__":

  loop = asyncio.get_event_loop()
  loop.run_until_complete(main())