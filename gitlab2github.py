#!/usr/bin/env python3

import os
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
      logger.debug(e)
    return -1

  # Create gitlab and github config dicts.
  gitlab_config = dict(cp["gitlab"])
  github_config = dict(cp["github"])

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
        logger.debug(e)

if __name__ == "__main__":

  loop = asyncio.get_event_loop()
  loop.run_until_complete(main())