Development
===========

Setup
-----

To get started with development, you'll need to install some dependencies and set up your development environment. Here are the steps you'll need to follow:

1. Create a virtual environment:

   ::

       virtualenv env
       source env/bin/activate

3. Install the project dependencies:

   ::

       pip install -r requirements.txt


Linting
-------

To ensure code quality and consistency, you can use the Pylint tool to check your code for errors and warnings. Here are the steps you'll need to follow:

Run pylint on specific files:

   ::

       pylint --rcfile=.pylintrc scripts/__init__.py
       pylint --rcfile=.pylintrc $(find . -name "*.py")


Pytest
------

To run tests for the project, you can use the pytest framework. Here are the steps you'll need to follow:
   
   ::

       pytest

   or

   ::

       pytest --cov --cov-report xml tests/

   to generate a code coverage report.


Sonar Scanner
-------------

To analyze your project's code quality, you can use the SonarQube platform with the Sonar Scanner tool. Here are the steps you'll need to follow:

1. Copy the `sonar-project.properties.sample` file to your project directory and rename it to `sonar-project.properties`:

   ::

       cp sonar-project.properties.sample sonar-project.properties

2. Open the `sonar-project.properties` file and replace the placeholder values with your own values:

   ::

       sonar.projectKey=your-project-key
       sonar.sources=.
       sonar.host.url=http://your-sonar-server-url:9000
       sonar.login=your-sonar-token
       sonar.python.coverage.reportPaths=coverage.xml

   Replace `your-project-key`, `your-sonar-server-url`, and `your-sonar-token` with your own values.

3. Run Sonar Scanner:

   ::

       sonar-scanner

   This will run the scanner and upload the analysis results to your SonarQube server.

For instructions on how to install SonarQube, please refer to the official documentation at: https://docs.sonarqube.org/latest/setup/install-server/
