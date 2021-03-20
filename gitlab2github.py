#!/usr/env/bin python3

import os
import aiohttp
import asyncio
import logging
import urllib.parse

async def main():

  debug = False

  gitlab_config = {
    "url": "https://gitlab.com/",
    "token": "",
    "project_id": "",
  }

  github_config = {
    "url": "https://api.github.com",
    "user": "",
    "token": "",
    "owner": "",
    "repo": "",
  }

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
  gitlab_milestones_merge_requests = results[3]

  # To create Github content, the order matters (some issues may have references to labels or milestones.)
  # Also, if labels or milestones fails, the program should stop (for the same reason).

  # Process labels.
  github_labels_tasks = []
  if gitlab_labels is not None:
    if len(gitlab_labels) > 0:

      logger.info("Creating Github tasks (labels)...")

      for label in gitlab_labels:
        json = {
          "name": label["name"],
          "description": label["description"],
          "color": label["color"]
        }
        github_labels_tasks.append(asyncio.create_task(github_create_label(logger, debug, github_config, json)))
    else:
      logger.info("There are no labels in this Gitlab project.")
  else:
    logger.info("Failed to retrieve labels from Gitlab.")
    return -1

  results = await asyncio.gather(*github_labels_tasks)
  logger.info("Tasks to create Github labels finished.")

  # await github_create_label(logger, github_config, "test")

  

########################################################################################################################
# Gitlab functions.
########################################################################################################################
async def get_gitlab_issues(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/issues".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab issues.")
      if debug:
        logger.debug(e)
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
        logger.debug(e)
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
        logger.debug(e)
      return None

async def get_gitlab_merge_requests(logger, debug, config):

  issues_url = urllib.parse.urljoin(config["url"], "/api/v4/projects/{project_id}/merge_requests".format(**config))
  headers = {'PRIVATE-TOKEN': config["token"]}
  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(issues_url, headers=headers) as response:
        return await response.json()
    except Exception as e:
      logging.error("Failed to retrive Gitlab merge requests.")
      if debug:
        logger.debug(e)
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
        logger.debug(e)
      return {"milestones": None}

if __name__ == "__main__":
  loop = asyncio.get_event_loop()
  loop.run_until_complete(main())