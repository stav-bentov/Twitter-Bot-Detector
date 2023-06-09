import datetime
from typing import Union
from Detector import detect_users_model, get_bots_in_followers
from Detector import load_model
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi import FastAPI 
import uvicorn
import redis
import asyncio
from collections import deque 

####### INIT REDIS #######
# Creating redis storage to store the results of the model from all users ever calculated
# values are stored in the following format:
# {username: {'classification': result, 'accuracy': accuracy_of_prediction, 'expiration': expirationDate}}
r = redis.Redis(host='localhost', port=6379, decode_responses=True)
#r.flushall() # delete all keys in redis storage

####### INIT MODEL #######
model = load_model() # load the model once

####### INIT requests QUEUE #######
# format: (usernames_list, future) per request
# notice that client need to wait for response before sending another request
requests_queue = deque() # global for all clients
PERIODIC_REQUESTS_CALCULATION = 2 # seconds

# global variable to indicate if process_requests task has started
process_requests_started = False

'''
returns: tuple:(all_users= list of all usernames on queue from all requests, number_of_calculated_requests= number of requests on queue)
'''
def get_all_usernames_on_queue():
    all_users = []
    for usernames_list, future in requests_queue:
        all_users += usernames_list 
    return all_users, len(requests_queue)
    
async def process_requests():
    while True: 
        if requests_queue: # is not empty
            all_users, number_of_calculated_requests = get_all_usernames_on_queue() 
            # Process the request and calculate the response
            response = detect_users_model(model, all_users)

            print("len(response) = ", len(response))
            # update the future object with the result from the model and pop from queue
            for i in range(number_of_calculated_requests):
                future = requests_queue.popleft()[1]
                future.set_result(response)

        await asyncio.sleep(PERIODIC_REQUESTS_CALCULATION)  # Wait for PERIODIC_REQUESTS_CALCULATION seconds before processing another up to 100 usernames

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/isBot/{usernames_str}")
async def is_bot(usernames_str: str):
    global process_requests_started
    result = {} # keys: usernames, values: {classification:user's classification (bot = 1, human = 0), accuracy:accuracy of prediction]

    usernames_list = usernames_str.split(",")
    #print("len before remove (usernames_list) = {0}".format(len(usernames_list)))

    # Update usernames_list to be only the usernames that are not in the redis storage
    for username in usernames_list:
        # If the username is in the redis storage:
        # 1. Get the result from redis storage
        # 2. Remove the username from the list of usernames that need to be calculated (by the model)
        if r.get(username) is not None:
            userStorageValue = eval(r.get(username)) # Convert string to userStorageValue dict
            expirationDate = datetime.datetime.strptime(str(userStorageValue['expiration']), '%Y-%m-%d %H:%M:%S.%f')
            if expirationDate > datetime.datetime.now(): # Redis value is still valid (has not expired yet)
                result[username] = {} # create new dict for the username
                result[username]['classification'] = userStorageValue['classification']
                result[username]['accuracy'] = userStorageValue['accuracy']
                usernames_list.remove(username) 

                """"""""""""""""" FOR TAMIR: """""""""""""""""
                """ Why not do 
                result[username] = {'classification': userStorageValue['classification'], 'accuracy': userStorageValue['accuracy']} # create new dict for the username"""
    
    # Calculates users in model and adds to the result
    if len(usernames_list) > 0: # cant send 0 users to model
        #print("usernames_list: {0}".format(usernames_list))

        # if process_requests not started yet, start the process_requests task in the background (only once)
        if not process_requests_started:
            asyncio.ensure_future(process_requests())
            process_requests_started = True

        future = asyncio.get_event_loop().create_future() 
        # Add usernames_list to the requests_queue
        requests_queue.append((usernames_list, future)) # future is the future object that will be updated with the result from the model
        response = await future # wait for the future to be updated with the result from the model
        # response is answer for all users request
        # update only the users that were in this request
        for username in usernames_list:
            if username in response:
                result[username] = response[username]        
    else:
        print("error: len(usernames_list) = {0}".format(len(usernames_list)))

    # Update redis storage with the **new** usernames and their results
    for username in usernames_list:
        expirationDate = datetime.datetime.now() + datetime.timedelta(days=30) # 30 days from now
        if username in result:
            userStorageValue = {'classification': result[username]['classification'], 'accuracy': result[username]['accuracy'] ,'expiration': expirationDate}
            userStorageValue = str(userStorageValue) # convert dict to string according to redis storage format
            r.set(username, userStorageValue)
        else:
            print("error: result = None for user: ", username, " maybe user does not exist anymore?")
    return result

@app.get("/followersBots/{username}")
async def followers_bots(username: str):
    # Assumption- there is not username with the name {username}_followers
    redis_user_key = f'{username}_followers'

    # If the result of username is saved and up to date- return its value
    """if r.get(redis_user_key) is not None:
        print("in redis!")
        userStorageValue = r.get(redis_user_key)
        expirationDate = datetime.datetime.strptime(str(userStorageValue['expiration']), '%Y-%m-%d %H:%M:%S.%f')
        if expirationDate <= datetime.datetime.now(): # Redis value is still valid (has not expired yet)
            return userStorageValue["bot_precentage"]"""
    
    # Else- calculate
    # Assumption sum(bot_prec) = 100
    result, bot_prec = get_bots_in_followers(model, username)

    # Update redis
    """expirationDate = datetime.datetime.now() + datetime.timedelta(days=30) # 30 days from now
    userStorageValue = {'bot_precentage': bot_prec[1], 'expiration': expirationDate}
    userStorageValue = str(userStorageValue) # Convert dict to string according to redis storage format
    r.set(redis_user_key, userStorageValue)"""

    return bot_prec[1]
    #return {"result": bot_prec[1]}
    
#app.add_middleware(HTTPSRedirectMiddleware)  # Redirect HTTP to HTTPS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this with the appropriate origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    #asyncio.run(uvicorn.run(app, port=8000))
    uvicorn.run(app, port=8000)
#uvicorn.run(app, host="0.0.0.0", port=3003, ssl_keyfile="./34.165.68.249-key.pem", ssl_certfile="./34.165.68.249.pem")