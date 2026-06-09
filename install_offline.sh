python3 -m venv deployment_env

source deployment_env/bin/activate

pip install \
--no-index \
--find-links=wheelhouse \
-r requirements.txt