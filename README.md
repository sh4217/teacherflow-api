Set up a virtual environment, install dependencies:
python3.11 -m venv venv
pip3 install -r requirements.txt

Activate the virtual environment, run the server:
source venv/bin/activate
cd api
python3 run.py

When finished:
deactivate