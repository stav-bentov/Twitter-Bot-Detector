from access_keys import bearer_token, consumer_key, consumer_secret, access_token_key, access_token_secret
import tweepy 
import sys 
from datetime import datetime
import pickle # for loading the model
import pandas as pd
from nltk.util import bigrams
from collections import Counter
import math
import time

# ========================================== Define variables ========================================== #
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')

client = tweepy.Client(bearer_token, wait_on_rate_limit = True) #,timeout = 3000)
default_image_url = "https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png"

# Define calculation of every feature [User will be response.data]
calculations = {"statuses_count": lambda User: User["public_metrics"]["tweet_count"],
                "followers_count": lambda User: User["public_metrics"]["followers_count"],
                "friends_count": lambda User: User["public_metrics"]["following_count"],
                "favourites_count": lambda User: get_liked_tweets(User["id"]),
                "listed_count": lambda User: User["public_metrics"]["listed_count"],
                "profile_use_background_image": lambda User: 1 if User["profile_image_url"] == default_image_url else 0, # boolean -> 0/1
                "verified": lambda User: 1 if User["verified"] else 0, # boolean -> 0/1

                "screen_name": lambda User: User["username"],
                "name": lambda User: User["name"],
                "description": lambda User: User["description"],

                "division": lambda x1,x2: x1/x2,
                "length": lambda str: len(str),
                "count_digits": lambda str: sum(char.isdigit() for char in str),
                "likelihood":  lambda str: likelihood(str),
                "user_age": lambda probe_time, created_at: (probe_time - created_at).total_seconds() / 3600 
                }

# Exsiting metadata
user_metadata_names = ["statuses_count", "followers_count","friends_count","favourites_count","listed_count","profile_use_background_image","verified"]

# Calculted features
user_derived_features = {"tweet_freq": [2, "statuses_count", "user_age", calculations["division"]],
                         "followers_growth_rate": [2, "followers_count", "user_age", calculations["division"]],
                         "friends_growth_rate": [2, "friends_count", "user_age", calculations["division"]],
                         "favourites_growth_rate": [2, "favourites_count", "user_age", calculations["division"]],
                         "listed_growth_rate": [2, "listed_count", "user_age", calculations["division"]],
                         "followers_friends_ratio": [2, "followers_count", "friends_count", calculations["division"]],
                         "screen_name_length": [1, "screen_name", calculations["length"]],
                         "num_digits_in_screen_name": [1, "screen_name", calculations["count_digits"]],
                         "name_length": [1, "name", calculations["length"]],
                         "num_digits_in_name": [1, "name", calculations["count_digits"]],
                         "description_length": [1, "description", calculations["length"]],
                         "screen_name_likelihood": [1, "screen_name", calculations["likelihood"]]}

# =============================================================================================== #
# ========================================== Functions ========================================== #
# =============================================================================================== #

def likelihood(str: str) -> float:
    """
        Input: string (screen_name/ name)
        Returns: The likelihood of the given string.
                 likelihood is defined by the geometric-mean likelihood of all bigrams in it.
    """
    # Create a list of all bigrams in str
    bigrams_list = list(bigrams(str))
    # Create a Dictonary with each bigram frequency
    bigrams_likelihood = Counter(bigrams_list)

    # Calculte number of all bigrams and number of different bigrams
    num_bigrams = len(bigrams_list)
    num_dif_bigrams = len(bigrams_likelihood)
    
    biagrams_mul = math.prod([value * (1/num_bigrams) for value in bigrams_likelihood.values()])

    # geometric-mean defenition
    return math.pow(biagrams_mul , (1/num_dif_bigrams))

def load_model():
    """
        Loads the model from detector_model.pkl
    """
    with open('detector_model.pkl', 'rb') as f: # rb = read binary
        model = pickle.load(f) # Load the model from the file
    return model

# TODO: later on, consider making a function for prediction of bunch of users
def model_predict_if_user_is_bot(model, user_metadata):
    """
        Input: 1) model. 2) user_metadata = a dictonary with features as keys and their corresponding values of the username
        Returns: 1 - bot, 0 - human
    """
    # Create a dataframe with the user_metadata
    df_user_data = pd.DataFrame(user_metadata, index=[0]) 

    # Predict the target
    prediction = model.predict(df_user_data) # Prediction [(0/1),...,] is list of predictions for many users, we only have 1 user
    return int(prediction[0]) # Return 1 if the user is a bot else- 0

def get_liked_tweets(user_id):
    """
        Input: gets user_id
        Returns: liked_tweets = favourites_count = number of tweets that the user liked
    """
    response = client.get_liked_tweets(id = user_id)
    # If the user liked at least 1 tweet -> response.data is not None
    if (response.data is not None):
        return len(response.data)
    return 0

def get_features(response_data):
    """
        Input: gets a dictonary with all metadata of current username
        Returns: a dictonary with features as keys and their corresponding values of the username
    """
    user_metadata = {}
    # Get the metadata from response.data and add to user_metadata
    for data in user_metadata_names:
        user_metadata[data] = calculations[data](response_data)

    # Calculate user_age for next features
    probe_time = datetime.now().replace(microsecond=0)
    created_at = datetime.fromisoformat(response_data["created_at"][:-1]).replace(tzinfo=None)
    user_age = calculations["user_age"](probe_time, created_at)

    # Add derived features to user_metadata
    for feature, calc in user_derived_features.items():
        if (feature == "favourites_growth_rate"):
            user_metadata[feature] = user_metadata["favourites_count"] / user_age
            continue
        num_variables = calc[0]
        calc_function = calc[-1]
        x1 = calculations[calc[1]](response_data)
        if (num_variables == 1):
            user_metadata[feature] = calc_function(x1)
        else: #else- num_variables == 2
            # max- Take care of a case where x2 = 0 (will get a devision by 0)
            x2 = max (user_age if calc[2] == "user_age" else calculations[calc[1]](response_data), 1)
            user_metadata[feature] = calc_function(x1, x2)

    return user_metadata

def detect_users(users):
    """
        Input: users- a list of usernames
        Returns: a dictonary with keys: usernames, values: user's classification (bot = 1, human = 0)
    """
    user_fields_param = ["name", "created_at", "description", "verified", "profile_image_url", "public_metrics", "id"]
    
    # client.get_users can get up to 100 users in a single request.
    req_max_size = 100
    res = {}
    
    # client.get_users can get up to 100 users, so we will separate our calls to up to 100
    for i in range(0, len(users), req_max_size):
        users_batch = users[i:i + req_max_size]

        # Creates a request with get_user - get response object which contains user object by username
        # RECALL: client.get_users is synchronous by default
        users_response = client.get_users(usernames = users_batch, user_fields = user_fields_param)
        time.sleep(0.5)
        for response in users_response.data:
            meta = get_features(response.data)
            res[response["username"]] = model_predict_if_user_is_bot(load_model(), meta)
    
    return res

def detect_user(username):
    meta = get_features(username)
    return model_predict_if_user_is_bot(load_model(), meta)

def detect_user_model(model, username):
    meta = get_features(username)
    return model_predict_if_user_is_bot(model, meta)

def detect_users_model(model, users):
    """
        Input: model- the model that classify our users
               users- a list of usernames
        Returns: a dictonary with keys: usernames, values: user's classification (bot = 1, human = 0)
    """
    user_fields_param = ["name", "created_at", "description", "verified", "profile_image_url", "public_metrics", "id"]
    
    # client.get_users can get up to 100 users in a single request.
    req_max_size = 100
    res = {}
    
    # client.get_users can get up to 100 users, so we will separate our calls to up to 100
    for i in range(0, len(users), req_max_size):
        users_batch = users[i:i + req_max_size]

        # Creates a request with get_user - get response object which contains user object by username
        # RECALL: client.get_users is synchronous by default
        users_response = client.get_users(usernames = users_batch, user_fields = user_fields_param)
        for response in users_response.data:
            meta = get_features(response.data)
            res[response["username"]] = model_predict_if_user_is_bot(model, meta)
    
    return res
#model = load_model()
#result = detect_users_model(model, ["YairNetanyahu","stav_1234"])
#print(result)
# meta = get_metadata("YairNetanyahu")
# print(model_predict_if_user_is_bot(load_model(), meta))