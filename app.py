from Detector import detect_user
from Detector import detect_user_model
from Detector import load_model

from flask import Flask
from flask import jsonify, make_response
from flask_cors import CORS
from flask_sslify import SSLify # for https

app = Flask(__name__)

# To avoid  No 'Access-Control-Allow-Origin' header is present on the requested resource.
CORS(app)
sslify = SSLify(app)  # Force HTTPS redirection
model = load_model() # load the model once

@app.route("/isBot/<string:username>/")
def is_bot(username):
    print("in backend for: ", username)
	# The return value from a function in a Flask app should be JSON serializable.
    result = 1 if detect_user_model(model, username) else 0 # 1 - bot, 0 - not bot
    return jsonify({username: result})

@app.route("/")
def home():
	print("in home")
	return "You are in Flask app for bot detection API"

if __name__ == '__main__':
	app.run(port=3003, host='0.0.0.0',ssl_context='adhoc', debug=True) # debug=True -> if there is an error, it will show on the screen