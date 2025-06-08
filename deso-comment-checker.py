import requests
import json
import threading  # For background calculations
import concurrent.futures
import time
from deso_sdk import DeSoDexClient
from deso_sdk  import base58_check_encode
import argparse
from pprint import pprint
import datetime
import re
import psutil
import logging
logging.basicConfig(format='%(asctime)s-%(levelname)s:[%(lineno)d]%(message)s', level=logging.INFO)

REMOTE_API = False
HAS_LOCAL_NODE_WITH_INDEXING = False
HAS_LOCAL_NODE_WITHOUT_INDEXING = True


BASE_URL = "https://node.deso.org"

seed_phrase_or_hex="" #dont share this
NOTIFICATION_UPDATE_INTERVEL = 30 #in seconds

api_url = BASE_URL+"/api/"
local_url= "http://localhost:17001"+"/api/"
prof_resp="PublicKeyToProfileEntryResponse"
tpkbc ="TransactorPublicKeyBase58Check"
pkbc="PublicKeyBase58Check"

# Global variables for thread control
stop_flag = True
calculation_thread = None
app_close=False
nodes={}
height=0
if REMOTE_API:
    HAS_LOCAL_NODE_WITHOUT_INDEXING= False
    HAS_LOCAL_NODE_WITH_INDEXING = False
else:
    if HAS_LOCAL_NODE_WITHOUT_INDEXING:
        HAS_LOCAL_NODE_WITH_INDEXING = False

    if HAS_LOCAL_NODE_WITH_INDEXING:
        HAS_LOCAL_NODE_WITHOUT_INDEXING = False

logging.debug(f"HAS_LOCAL_NODE_WITHOUT_INDEXING:{HAS_LOCAL_NODE_WITHOUT_INDEXING}")
logging.debug(f"HAS_LOCAL_NODE_WITH_INDEXING:{HAS_LOCAL_NODE_WITH_INDEXING}")


client = DeSoDexClient(
    is_testnet=False,
    seed_phrase_or_hex=seed_phrase_or_hex,
    passphrase="",
    node_url=BASE_URL if REMOTE_API else "http://localhost:17001"
)


def api_get(endpoint, payload=None,version=0):
    try:
        if REMOTE_API:
            response = requests.post(api_url +"v"+str(version)+"/"+ endpoint, json=payload)
        else:
            if HAS_LOCAL_NODE_WITHOUT_INDEXING:
                if endpoint=="get-notifications":
                    logging.debug("---Using remote node---")
                    response = requests.post(api_url +"v"+str(version)+"/"+ endpoint, json=payload)
                    logging.debug("--------End------------")
                else:
                    response = requests.post(local_url +"v"+str(version)+"/"+ endpoint, json=payload)
            if HAS_LOCAL_NODE_WITH_INDEXING:
                response = requests.post(local_url +"v"+str(version)+"/"+ endpoint, json=payload)
        
            
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"API Error: {e}")
        return None
def node_info():
    payload = {
    }
    data = api_get("node-info", payload,1)
    return data

def get_app_state():
    payload = {
    }
    data = api_get("get-app-state", payload)
    return data
def get_single_profile(Username,PublicKeyBase58Check=""):
    payload = {
        "NoErrorOnMissing": False,
        "PublicKeyBase58Check": PublicKeyBase58Check,
        "Username": Username
    }
    data = api_get("get-single-profile", payload)
    return data


bot_public_key = base58_check_encode(client.deso_keypair.public_key, False)
bot_username = get_single_profile("",bot_public_key)["Profile"]["Username"]
if bot_username is None:
    logging.error("Error,bot username can not get. exit")
    exit()

if info:=get_app_state():
    nodes=info["Nodes"]
    height=info["BlockHeight"]

def get_quote_reposts_for_post(PostHashHex,ReaderPublicKeyBase58Check):
    payload = {
        "Limit":50,
        "Offset":0,
        "PostHashHex": PostHashHex,
        "ReaderPublicKeyBase58Check":ReaderPublicKeyBase58Check
    }
    data = api_get("get-quote-reposts-for-post", payload)
    return data

def get_reposts_for_post(PostHashHex,ReaderPublicKeyBase58Check):
    payload = {
        "Limit":50,
        "Offset":0,
        "PostHashHex": PostHashHex,
        "ReaderPublicKeyBase58Check":ReaderPublicKeyBase58Check
    }
    data = api_get("get-reposts-for-post", payload)
    return data

def get_single_post(post_hash_hex, reader_public_key=None, fetch_parents=False, comment_offset=0, comment_limit=100, add_global_feed=False):
    payload = {
        "PostHashHex": post_hash_hex,
        "FetchParents": fetch_parents,
        "CommentOffset": comment_offset,
        "CommentLimit": comment_limit
    }
    if reader_public_key:
        payload["ReaderPublicKeyBase58Check"] = reader_public_key
    if add_global_feed:
        payload["AddGlobalFeedBool"] = add_global_feed
    data = api_get("get-single-post", payload)
    return data["PostFound"] if "PostFound" in data else None

def get_notifications(PublicKeyBase58Check,FetchStartIndex=-1,NumToFetch=1,FilteredOutNotificationCategories={}):
    payload = {
        "PublicKeyBase58Check": PublicKeyBase58Check,
        "FetchStartIndex": FetchStartIndex,
        "NumToFetch": NumToFetch,
        "FilteredOutNotificationCategories":FilteredOutNotificationCategories
    }
    data = api_get("get-notifications", payload)
    return data


def create_post(body,parent_post_hash_hex):
    logging.info("\n---- Submit Post ----")
    try:
        logging.info('Constructing submit-post txn...')
        post_response = client.submit_post(
            updater_public_key_base58check=bot_public_key,
            body=body,
            parent_post_hash_hex=parent_post_hash_hex,  # Example parent post hash
            title="",
            image_urls=[],
            video_urls=[],
            post_extra_data={"Node": "1"},
            min_fee_rate_nanos_per_kb=1000,
            is_hidden=False,
            in_tutorial=False
        )
        logging.info('Signing and submitting txn...')
        submitted_txn_response = client.sign_and_submit_txn(post_response)
        txn_hash = submitted_txn_response['TxnHashHex']
        
        logging.info('SUCCESS!')
        return 1
    except Exception as e:
        logging.error(f"ERROR: Submit post call failed: {e}")
        return 0


def save_to_json(data, filename):
  try:
    with open(filename, 'w') as f:  # 'w' mode: write (overwrites existing file)
      json.dump(data, f, indent=4)  # indent for pretty formatting
    logging.info(f"Data saved to {filename}")
  except TypeError as e:
    logging.error(f"Error: Data is not JSON serializable: {e}")
  except Exception as e:
    logging.error(f"Error saving to file: {e}")

def load_from_json(filename):
  try:
    with open(filename, 'r') as f:  # 'r' mode: read
      data = json.load(f)
    logging.info(f"Data loaded from {filename}")
    return data
  except FileNotFoundError:
    logging.error(f"Error: File not found: {filename}")
    return None  # Important: Return None if file not found
  except json.JSONDecodeError as e:
    logging.error(f"Error decoding JSON in {filename}: {e}")
    return None # Important: Return None if JSON is invalid
  except Exception as e:
    logging.error(f"Error loading from file: {e}")
    return None

def parse_state(paragraph):
    pattern = r'@commentchecker\s+(on(?:\s+\w+)?|off(?:\s+all)?|info)\b'

    # Value mapping
    value_map = {
        'on': 'on',
        'off': 'off',
        'off all': 'off_all',
        'info': 'info',
        'on basic': 'basic'  # new support for 'on basic'
    }

    # Search only for the first match
    match = re.search(pattern, paragraph, re.IGNORECASE)

    result = None

    if match:
        full_command = match.group(0)
        param = match.group(1).lower()
        # Normalize
        if param.startswith('off') and 'all' in param:
            param = 'off all'
        elif param.startswith('on') and 'basic' in param:
            param = 'on basic'
        value = value_map.get(param)
        result = {'command': full_command, 'value': value}

    # Output result
    logging.debug(result)
    return result
    
def check_comment(transactor,postId,parent_post_list,parent_post,comment,data_save,comment_level,notify=False):
    logging.debug(f"Comment Level:{comment_level}")
    if comment_level==0:
        logging.debug(postId)
        logging.debug("check for reposts")
        if parent_post["RepostCount"]>0:
            if result:=get_reposts_for_post(parent_post["PostHashHex"],transactor):
                    logging.debug("Reposters:")
                    for r in result["Reposters"]:
                        #logging.debug(r)
                        logging.debug(r["PublicKeyBase58Check"])
                        parent_post_list[transactor][postId]["Reposters"] = parent_post_list[transactor][postId].get("Reposters",[])
                        if r["PublicKeyBase58Check"] not in parent_post_list[transactor][postId]["Reposters"]:
                            logging.info("+++New repost detected")
                            parent_post_list[transactor][postId]["Reposters"].append(r["PublicKeyBase58Check"])
                            data_save[0]=True
        if parent_post["QuoteRepostCount"]>0:
                if result:=get_quote_reposts_for_post(parent_post["PostHashHex"],transactor):
                    logging.debug("Quote Reposters:")
                    for r in result["QuoteReposts"]:
                        logging.debug(r["PosterPublicKeyBase58Check"])
                        logging.debug(r["PostHashHex"])
                        parent_post_list[transactor][postId]["QuoteReposters"] = parent_post_list[transactor][postId].get("QuoteReposters",[])
                        if r["PostHashHex"] not in parent_post_list[transactor][postId]["QuoteReposters"]:
                            logging.info("+++New quote repost detected")
                            thread_owner = parent_post["ProfileEntryResponse"]["Username"]
                            thread_owner_id = parent_post["ProfileEntryResponse"]["PublicKeyBase58Check"]

                            try: 
                                url="https://diamondapp.com/posts/"
                                trigger_post=get_single_post(postId, transactor)
                                if "Node" in trigger_post["PostExtraData"]:
                                    if node_id:=trigger_post["PostExtraData"]["Node"]:
                                        url = nodes[node_id]["URL"]+"/posts/"
                            except Exception as e:
                                logging.error(e)   
                            username = r["ProfileEntryResponse"]["Username"]
                            quote_reposter_id=r["ProfileEntryResponse"]["PublicKeyBase58Check"]
                            if notify and transactor!=thread_owner_id and transactor!=quote_reposter_id:
                                
                                post_body = f"{username} Quote Resposted {thread_owner}'s thread:\n{url}{r["PostHashHex"]}"
                                parent_post_link = parent_post_list[transactor][postId]["ParentPostHashHex"]
                                mode = parent_post_list[transactor][postId].get("mode","basic")
                                body = r["Body"]
                                if mode == "basic":
                                    post_body = f"{username} Quote Resposted {thread_owner}'s thread:\n{url}{r["PostHashHex"]}"
                                elif mode =="full":
                                    post_body=f"{username} Quote Resposted {thread_owner}'s thread:\n{url}{parent_post_link}\n\n{username} -> {thread_owner}'s Post\n\nContent:\n{body}\n\nQuote Repost Link:\n{url}{r["PostHashHex"]}"
                            
                                create_post(post_body,postId)
                                logging.debug(post_body)
                            elif transactor==thread_owner_id:
                                logging.info("Quote repost already handled by deso")
                            parent_post_list[transactor][postId]["QuoteReposters"].append(r["PostHashHex"])
                            data_save[0]=True




    if comment["CommentCount"]>0:   #this post/comment has no comments,exit
        comment_level +=1
        #single_post_details=get_single_post(comment["PostHashHex"], transactor)
        upper_user=comment["ProfileEntryResponse"]["Username"]
        upper_user_id=comment["ProfileEntryResponse"]["PublicKeyBase58Check"]
        
        if comments := comment["Comments"]:
           
            for comment in comments:
                username = comment["ProfileEntryResponse"]["Username"]
                commenter_id=comment["ProfileEntryResponse"]["PublicKeyBase58Check"]

                if comment["PostHashHex"] not in parent_post_list[transactor][postId]["Comments"]:
                    
                    body=comment["Body"]
                    comment_id=comment["PostHashHex"] 
                    
                    if (username!=bot_username and commenter_id!=transactor and upper_user_id!=transactor) and notify:  #avoid same bot comment notification infinit loop
                        try:
                            logging.info(f"New comment detected")
                            parent_post_link = parent_post_list[transactor][postId]["ParentPostHashHex"]
                            
                            mode = parent_post_list[transactor][postId].get("mode","basic")
                            logging.debug("Getting node details of transactor")
                            thread_owner = parent_post["ProfileEntryResponse"]["Username"]
                            thread_owner_id = parent_post["ProfileEntryResponse"]["PublicKeyBase58Check"]
                            try: 
                                url="https://diamondapp.com/posts/"
                                trigger_post=get_single_post(postId, transactor)
                                if "Node" in trigger_post["PostExtraData"]:
                                    #logging.info(trigger_post["PostExtraData"])
                                    #logging.info(nodes)
                                    if node_id:=trigger_post["PostExtraData"]["Node"]:
                                        url = nodes[node_id]["URL"]+"/posts/"
                            except Exception as e:
                                logging.error(e)  
                            logging.debug(url)
                            if mode == "basic":
                                post_body = f"{username} commented on {thread_owner}'s thread:\n{url}{comment_id}"
                            elif mode =="full":
                                post_body=f"{username} commented on {thread_owner}'s thread:\n{url}{parent_post_link}\n\n{username} -> {upper_user}'s comment/post\n\nContent:\n{body}\n\nComment Link:\n{url}{comment_id}"
                            
                            modified_text = post_body.replace("@", "(@)")
                            logging.debug(post_body)
                            
                            create_post(modified_text,postId)
                            
                            data_save[0]=True
                        except Exception as e:
                            logging.error(e)
                    elif username==bot_username:
                        logging.debug("Avoiding my own comment trigger")
                    elif commenter_id==transactor or upper_user_id==transactor:
                        logging.debug("Avoiding because native notification is doing it")
                    elif not notify:
                        logging.debug("Initial posts thread scanning to get comments when mentioned")
                    
                    if username!=bot_username:
                        parent_post_list[transactor][postId]["Comments"].append(comment["PostHashHex"])
                        #save_to_json(parent_post_list,"parentPostList.json")
                    
                logging.debug(f"[{comment_level}]Comment")
                if postId!=comment["PostHashHex"] and username!=bot_username:
                    
                    check_comment(transactor,postId,parent_post_list,parent_post,comment,data_save,comment_level,notify)
                elif postId==comment["PostHashHex"]:
                    logging.debug("commentchecker on post skipping")
                elif username==bot_username:
                    logging.debug("My own comments skipping")


def notificationListener():
    counter=0
    profile=get_single_profile("",bot_public_key)
    post_id_list=[]
    parent_post_list={}
    last_run = datetime.datetime.now() - datetime.timedelta(hours=1)

    lastIndex=-1
    
    if result:=load_from_json("notificationLastIndex_thread.json"):
        lastIndex=result["index"]

    maxIndex=lastIndex

    if result:=load_from_json("postIdList_thread.json"):
        post_id_list=result["post_ids"]

    if result:=load_from_json("parentPostList.json"):
        parent_post_list = result

    while not app_close:
        try:
            start_time = time.time()
            
            currentIndex=-1
            # if result:=load_from_json("notificationLastIndex_thread.json"):
            #     lastIndex=result["index"]
            logging.debug(f"lastIndex:{lastIndex}")

            i=0
            while i<20:#max 20 iteration, total 400 notifications check untill last check index
                i +=1 
                logging.debug(f"currentIndex:{currentIndex}")
                result=get_notifications(profile["Profile"]["PublicKeyBase58Check"],FetchStartIndex=currentIndex,NumToFetch=20,FilteredOutNotificationCategories={"dao coin":True,"user association":True, "post association":True,"post":False,"dao":True,"nft":True,"follow":True,"like":True,"diamond":True,"transfer":True})
                for notification in result["Notifications"]:
                
                    currentIndex = notification["Index"]
                    logging.debug(f"currentIndex:{currentIndex}")

                    if notification["Index"]>maxIndex: #new mentions
                        logging.info("New mentions")
                        maxIndex = notification["Index"]
                    if currentIndex<lastIndex:
                        logging.debug("Exiting notification loop, currentIndex<lastIndex")
                        break

                            
                    for affectedkeys in notification["Metadata"]["AffectedPublicKeys"]:
                        if affectedkeys["Metadata"]=="MentionedPublicKeyBase58Check":
                            if affectedkeys["PublicKeyBase58Check"]==profile["Profile"]["PublicKeyBase58Check"]:
                                postId=notification["Metadata"]["SubmitPostTxindexMetadata"]["PostHashBeingModifiedHex"]
                                if postId in post_id_list:
                                    break
                                else:
                                    post_id_list.append(postId)
                                    logging.info(postId)
                                    transactor=notification["Metadata"]["TransactorPublicKeyBase58Check"]
                                    r=get_single_profile("",transactor)
                                    if r is None:
                                        break
                                    username= r["Profile"]["Username"]
                                    mentioned_post = get_single_post(postId,bot_public_key)
                                    body=mentioned_post["Body"]
                                
                                    logging.debug(f"username: {username}")
                                    logging.debug(f"transactor: {transactor}")
                                    logging.debug(f"body:\n{body}") 
                                    status_res=parse_state(body)
                                    if status_res is None:
                                        status=None
                                    else:
                                        status=status_res["value"]

                                    logging.debug(f"Status:{status}")

                                    parent_post = [{"test":1}]
                                    logging.info("Start check parent post=>")
                                    parent_post_id = postId
                                    while len(parent_post)>0:
                                        post_result=get_single_post(parent_post_id, transactor, fetch_parents=True)
                                        parent_post=post_result["ParentPosts"]
                                        if len(parent_post)>0:
                                            parent_post_id = parent_post[0]["PostHashHex"]
                                        
                                    logging.debug(parent_post_id)
                                    if status is None:
                                        status = "basic"

                                    if status is not None:
                                        if status=="on" or status=="basic":
                                            present=False
                                            if transactor in parent_post_list:
                                                for mentioned_post in parent_post_list[transactor]:
                                                    if parent_post_list[transactor][mentioned_post]["ParentPostHashHex"]==parent_post_id:
                                                        present=True
                                            if not present:
                                                parent_post_list[transactor] = parent_post_list.get(transactor,{})
                                                parent_post_list[transactor][postId] = parent_post_list[transactor].get(postId,{})
                                                logging.info("------Adding thread notification------")
                                                parent_post_list[transactor][postId]["ParentPostHashHex"] = parent_post_id
                                                single_post_details=get_single_post(parent_post_id, transactor)
                                                parent_post_list[transactor][postId]["Comments"]=parent_post_list[transactor][postId].get("Comments",[]) 
                                                if status=="basic":
                                                    parent_post_list[transactor][postId]["mode"] = "basic"
                                                else:
                                                    parent_post_list[transactor][postId]["mode"] = "full"
                                                create_post("You have registered this thread with "+parent_post_list[transactor][postId]["mode"]+" option",postId) 
                                                   
                                                data_save= [False]
                                                comment_level=0
                                                check_comment(transactor,postId,parent_post_list,single_post_details,single_post_details,data_save,comment_level,notify=False)  
                                            else:
                                                logging.debug("Already registered")
                                                create_post("Already registered",postId) 
                                        elif status=="off":
                                            try:
                                                for id in parent_post_list[transactor]:
                                                    if(parent_post_list[transactor][id]["ParentPostHashHex"]==parent_post_id):
                                                        logging.info("------Deleting thread notification------")
                                                        
                                                        create_post("Deleted this post thread notification",postId) 
                                                        create_post("Deleted this post thread notification",id) 
                                                        del parent_post_list[transactor][id]
                                                        break
                                            except Exception as e:
                                                logging.error("Error deleting")
                                                logging.error(e)
                                   
                                        elif status=="off_all":
                                            try:
                                                logging.info("------Deleting all "+username+" thread notification------")
                                                for id in parent_post_list[transactor]:
                                                    create_post("Deleted this post thread notification",id) 
                                                    del parent_post_list[transactor][id]
                                                    save_to_json(parent_post_list,"parentPostList.json")

                                                create_post("Deleted all posts threads notification",postId) 
                                                del parent_post_list[transactor]
                                                
                                                
                                            except Exception as e:
                                                logging.error("Error deleting")
                                                logging.error(e)
                                        elif status=="info":
                                            try:
                                                link_count=0
                                                logging.info("------info thread notification------")
                                                reply_body=username+" Registered Posts Threads\n\n"

                                                p=get_single_post(postId, transactor)
                            
                                                if node_id:=p["PostExtraData"]["Node"]:
                                                    if node_id in nodes:
                                                        url = nodes[node_id]["URL"]+"/posts/"
                                                    else:
                                                        url="https://diamondapp.com/posts/"
                                                else:
                                                    url="https://diamondapp.com/posts/"
                                                logging.debug(url)
                                                if transactor in parent_post_list:
                                                    
                                                    for mentioned_posts in parent_post_list[transactor]:
                                                        r = get_single_post(parent_post_list[transactor][mentioned_posts]["ParentPostHashHex"], transactor)
                                                        thread_owner = r["ProfileEntryResponse"]["Username"]
                                                        link_count += 1
                                                        reply_body += "["+str(link_count)+"] "+thread_owner+"\n"+url+str(parent_post_list[transactor][mentioned_posts]["ParentPostHashHex"])+"\n"
                                                        
                                                    logging.debug(reply_body)
                                                create_post(reply_body,postId)        
                                                
                                            except Exception as e:
                                                logging.error("Error deleting")
                                                logging.error(e)

                                    save_to_json({"post_ids":post_id_list},"postIdList_thread.json")
                                    save_to_json(parent_post_list,"parentPostList.json")
                                   
                                    break
                if notification["Index"]<20: #end of mentions
                    logging.debug("End of mentions")
                    break 
                if currentIndex<=lastIndex:
                    logging.debug("Exiting while loop, currentIndex<=lastIndex")
                    break

            if maxIndex > lastIndex:
                logging.debug("maxIndex > lastIndex")
                lastIndex = maxIndex
                save_to_json({"index":lastIndex},"notificationLastIndex_thread.json")

            users_count=len(parent_post_list)
            posts_scan=0
            threads=0
            for users in parent_post_list:
                threads += len(parent_post_list[users])
                for mentioned_post in parent_post_list[users]:
                    posts_scan += len(parent_post_list[users][mentioned_post]["Comments"])
                
            logging.info(f"Number of users registered:{users_count}")
            logging.info(f"Number of Threads added:{threads}")
            logging.info(f"Number of comments to scan:{posts_scan}")
            
    
            counter +=1
            now = datetime.datetime.now(datetime.timezone.utc)
            # Calculate the time 'days_ago' days ago as a datetime object.
            past_datetime = now - datetime.timedelta(days=90)
            # Convert the past datetime object to a Unix timestamp.
            past_timestamp = time.mktime(past_datetime.timetuple())

            end_time = time.time()
            if counter>=1:
                counter=0
                for transactor,userdata in parent_post_list.items():
                    data_save = [False]
                    comment_level=0
                    logging.debug(transactor)
                    for postId,data in userdata.items():
                        #check if expired
                        if mentioned_post := get_single_post(postId,transactor):
                            if mentioned_post["TimestampNanos"]/1e9 < past_timestamp:
                                del parent_post_list[transactor][postId]
                                create_post("Deleted this post thread notification (expired)",postId) 
                                continue  

                        if single_post_details:=get_single_post(data["ParentPostHashHex"], transactor):
                            parent_post_list[transactor][postId]["Comments"]=parent_post_list[transactor][postId].get("Comments",[])
                            logging.debug("Checking comment->")
                            check_comment(transactor,postId,parent_post_list,single_post_details,single_post_details,data_save,comment_level,notify=True)
                                

                            #pprint(comment)
                    if data_save[0]:
                        save_to_json(parent_post_list,"parentPostList.json")
                logging.debug("End")

                if info:=get_app_state():
                    nodes=info["Nodes"]
                    height=info["BlockHeight"]

                

                mem = psutil.virtual_memory()
                info_body="✍️ Comment Checker Service Status\n"
                info_body +=f"* Number of users registered: {users_count}\n"
                info_body +=f"* Number of Posts Threads added: {threads}\n"
                info_body +=f"* Number of comments to scan: {posts_scan}\n"
                info_body +=f"* Comments Scan time: {end_time - start_time:.4f} seconds\n\n"
                info_body +=f"🖥️ DeSo Node Server Status\n"
                info_body +=f"* Block Height: {height}\n"
                info_body +=f"* Total RAM memory: {mem.total / (1024 ** 3):.1f} GB\n"
                info_body +=f"* Used RAM memory: {mem.used / (1024 ** 3):.1f} GB\n"
                info_body +=f"* Available RAM memory: {mem.available / (1024 ** 3):.1f} GB\n"
                info_body +=f"* RAM Memory usage: {mem.percent}%\n"
                # if info:=node_info():
                #     pprint(info)
                #print(f"Comments Scan time: {end_time - start_time:.4f} seconds")
                

                logging.debug(info_body)

                now = datetime.datetime.now()
    
                if now - last_run >= datetime.timedelta(hours=1):
                    create_post(info_body,"")
                    last_run = now

            for _ in range(NOTIFICATION_UPDATE_INTERVEL):
                time.sleep(1)
                if app_close: 
                    return
        except Exception as e:
            logging.error(e)
            time.sleep(100)


notificationListener()

