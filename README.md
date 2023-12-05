![AgriCatch Logo](https://azdv.github.io/agricatch/images/logo.png)
=========

# AgriCatch - Data Aggregation Library for Django

AgriCatch is a robust data aggregation library designed for Django applications. It facilitates the extraction and management of data across a wide array of sources, tailored specifically for web crawling at scale.

## Background

AgriCatch has evolved through multiple iterations, from its initial conception in Vanilla PHP, transitioning through the Yii framework, and finally finding its home in Python. The latest incarnation harnesses the power of Django, embracing the full potential of Python 3.

## Getting Started

Before you begin, ensure that you have Django installed in your environment. AgriCatch is built on top of Django's robust framework, leveraging its ORM and management commands.

### Initial Setup

To set up your database and prepare the environment, run the following commands:

```bash
python manage.py syncdb
```

### Importing Data

AgriCatch simplifies the import process from various sources. To import data, execute the command below:

```bash
python manage.py doimport [source]
```

Replace `[source]` with the name of the website or data source you wish to import from. For example, to import from Gizmodo:

```bash
python manage.py doimport gizmodo
```

## File Structure

- `manage.py`: The command-line utility for administrative tasks.
- `agricatch/`:
  - `settings.py`: Contains all the settings for the AgriCatch project.
  - `urls.py`: The URL declarations for the AgriCatch project.
  - `website.py`: Defines the generic Website class for data aggregation.
- `agricatch/helpers/`:
  - `general.py`: General helper functions for the application.
  - `importhelper.py`: Helper functions specifically tailored for importing and processing data.
- `agricatch/management/commands/`:
  - `doimport.py`: Management command to import data from specified sources.
  - `localizr.py`: Management command for geolocating places without coordinates.
- `agricatch/tech/`:
  - `models.py`: Django models for the application.
  - `helpers/`: Additional helper functions for view logic.
  - `websites/`: Individual Python scripts for each website to be crawled.

## Configuration

Modify the `agricatch/settings.py` file to suit your database configuration and environmental settings. Pay special attention to the `DATABASES` configuration to connect to your chosen database system.

## Models

AgriCatch uses Django models to represent the data structure. The `Article` and `Website` models can be found in `agricatch/tech/models.py`. Extend or modify these models based on the data you expect to handle.

## Logging

Logging configuration is set up in `agricatch/settings.py`. By default, logs are written to `logs/agricatch.log`. Ensure the logs directory is writable.

## Contribute

Contributions to AgriCatch are welcome. Extend the functionality by adding new website scripts in `agricatch/tech/websites/` or enhance existing ones.
