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

blacklist = ["greenwork32","globalnetwork22"]  #bots accounts username list

BASE_URL = "https://node.deso.org"

seed_phrase_or_hex="" #dont share this
NOTIFICATION_UPDATE_INTERVEL = 30 #in seconds

api_url = BASE_URL+"/api/v0/"
prof_resp="PublicKeyToProfileEntryResponse"
tpkbc ="TransactorPublicKeyBase58Check"
pkbc="PublicKeyBase58Check"

# Global variables for thread control
stop_flag = True
calculation_thread = None
app_close=False


client = DeSoDexClient(
    is_testnet=False,
    seed_phrase_or_hex=seed_phrase_or_hex,
    passphrase="",
    node_url=BASE_URL
)

def api_get(endpoint, payload=None):
    try:
        response = requests.post(api_url + endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

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
    print("Error,bot username can not get. exit")
    exit()



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
    print("\n---- Submit Post ----")
    try:
        print('Constructing submit-post txn...')
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
        print('Signing and submitting txn...')
        submitted_txn_response = client.sign_and_submit_txn(post_response)
        txn_hash = submitted_txn_response['TxnHashHex']
        client.wait_for_commitment_with_timeout(txn_hash, 30.0)
        print('SUCCESS!')
        return 1
    except Exception as e:
        print(f"ERROR: Submit post call failed: {e}")
        return 0


def save_to_json(data, filename):
  try:
    with open(filename, 'w') as f:  # 'w' mode: write (overwrites existing file)
      json.dump(data, f, indent=4)  # indent for pretty formatting
    print(f"Data saved to {filename}")
  except TypeError as e:
    print(f"Error: Data is not JSON serializable: {e}")
  except Exception as e:
    print(f"Error saving to file: {e}")

def load_from_json(filename):
  try:
    with open(filename, 'r') as f:  # 'r' mode: read
      data = json.load(f)
    print(f"Data loaded from {filename}")
    return data
  except FileNotFoundError:
    print(f"Error: File not found: {filename}")
    return None  # Important: Return None if file not found
  except json.JSONDecodeError as e:
    print(f"Error decoding JSON in {filename}: {e}")
    return None # Important: Return None if JSON is invalid
  except Exception as e:
    print(f"Error loading from file: {e}")
    return None

def parse_state(paragraph):
    paragraph = paragraph.lower()  # make case-insensitive

    if re.search(r'\b(on|enable|1)\b', paragraph):
        return 1
    elif re.search(r'\b(off|disable|0)\b', paragraph):
        return 0
    else:
        return None
    
def check_comment(transactor,postId,parent_post_list,comment,get_single_post,data_save,comment_level,notify=False):
                if comment["CommentCount"]>0:
                    single_post_details=get_single_post(comment["PostHashHex"], transactor)
                    comment_level +=1
                    if comments := single_post_details["Comments"]:
                        for comment in comments:
                            if comment["PostHashHex"] not in parent_post_list[transactor][postId]["Comments"]:
                                print(f"New comment detected")
                                body=comment["Body"]
                                comment_id=comment["PostHashHex"] 
                                # r=get_single_profile("",transactor)
                                # username= r["Profile"]["Username"]
                                username = comment["ProfileEntryResponse"]["Username"]
                                if username!=bot_username and notify:  #avoid same bot comment notification infinit loop
                                    parent_post_link = parent_post_list[transactor][postId]["ParentPostHashHex"]
                                    post_body=f"{username} commented on this thread:\nhttps://diamondapp.com/posts/{parent_post_link}\n\nContent:\n{body}\n\nComment:\nhttps://diamondapp.com/posts/{comment_id}"
                                    print(post_body)
                                    modified_text = post_body.replace("@", "(@)")
                                    print("Posting")
                                    create_post(modified_text,postId)
                                parent_post_list[transactor][postId]["Comments"].append(comment["PostHashHex"])
                                data_save = True
                            print(f"[{comment_level}]Comment:")
                            
                            check_comment(transactor,postId,parent_post_list,comment,get_single_post,data_save,comment_level,notify)

def notificationListener():
    profile=get_single_profile("",bot_public_key)
    post_id_list=[]
    parent_post_list={}
    if result:=load_from_json("postIdList_thread.json"):
        post_id_list=result["post_ids"]

    if result:=load_from_json("parentPostList.json"):
        parent_post_list = result

    while not app_close:
        try:
            lastIndex=-1
            currentIndex=-1
            if result:=load_from_json("notificationLastIndex_thread.json"):
                lastIndex=result["index"]
            print(f"lastIndex:{lastIndex}")
            first=True
            i=0

            while i<10:#max 10 iteration, total 200 notifications check untill last check index
                i +=1 
                print(f"currentIndex:{currentIndex}")
                result=get_notifications(profile["Profile"]["PublicKeyBase58Check"],FetchStartIndex=currentIndex,NumToFetch=20,FilteredOutNotificationCategories={"dao coin":True,"user association":True, "post association":True,"post":False,"dao":True,"nft":True,"follow":True,"like":True,"diamond":True,"transfer":True})
                for notification in result["Notifications"]:
                
                    currentIndex = notification["Index"]
                    if first:
                        first=False
                        save_to_json({"index":notification["Index"]},"notificationLastIndex_thread.json")
                            
                    for affectedkeys in notification["Metadata"]["AffectedPublicKeys"]:
                        if affectedkeys["Metadata"]=="MentionedPublicKeyBase58Check":
                            if affectedkeys["PublicKeyBase58Check"]==profile["Profile"]["PublicKeyBase58Check"]:
                                postId=notification["Metadata"]["SubmitPostTxindexMetadata"]["PostHashBeingModifiedHex"]
                                if postId in post_id_list:
                                    break
                                else:
                                    post_id_list.append(postId)
                                    print(postId)
                                    transactor=notification["Metadata"]["TransactorPublicKeyBase58Check"]
                                    r=get_single_profile("",transactor)
                                    username= r["Profile"]["Username"]
                                    mentioned_post = get_single_post(postId,bot_public_key)
                                    body=mentioned_post["Body"]
                                    #check if on or off
                                    print(f"username{username}")
                                    print(f"transactor{transactor}")
                                    print(f"body{body}") 
                                    status=parse_state(body)
                                    print(f"Status:{status}")

                                    parent_post = [{"test":1}]
                                    print("Start check parent post=>")
                                    parent_post_id = postId
                                    while len(parent_post)>0:
                                        post_result=get_single_post(parent_post_id, transactor, fetch_parents=True)
                                        parent_post=post_result["ParentPosts"]
                                        if len(parent_post)>0:
                                            parent_post_id = parent_post[0]["PostHashHex"]
                                        
                                    print(parent_post_id)
                                    
                                    

                                    parent_post_list[transactor] = parent_post_list.get(transactor,{})
                                    
                                    if status==1:
                                        parent_post_list[transactor][postId] = parent_post_list[transactor].get(postId,{})
                                        print("------Adding thread notification------")
                                        parent_post_list[transactor][postId]["ParentPostHashHex"] = parent_post_id
                                        single_post_details=get_single_post(parent_post_id, transactor)
                                        parent_post_list[transactor][postId]["Comments"]=parent_post_list[transactor][postId].get("Comments",[]) 
                                        data_save = False
                                        comment_level=0
                                        check_comment(transactor,postId,parent_post_list,single_post_details,get_single_post,data_save,comment_level,notify=False)  
                                    else:
                                        try:
                                            for id in parent_post_list[transactor]:
                                                if(parent_post_list[transactor][id]["ParentPostHashHex"]==parent_post_id):
                                                    print("------Deleting thread notification------")
                                                    del parent_post_list[transactor][id]
                                                    break
                                        except KeyError:
                                            pass
                                        #print(parent_post_list)

                                    save_to_json({"post_ids":post_id_list},"postIdList_thread.json")
                                    save_to_json(parent_post_list,"parentPostList.json")

                                    break
                if currentIndex<=lastIndex:
                    break
            

            for transactor,userdata in parent_post_list.items():
                data_save = False
                comment_level=0
                print(transactor)
                for postId,data in userdata.items():
                    single_post_details=get_single_post(data["ParentPostHashHex"], transactor)
                    parent_post_list[transactor][postId]["Comments"]=parent_post_list[transactor][postId].get("Comments",[])
                    check_comment(transactor,postId,parent_post_list,single_post_details,get_single_post,data_save,comment_level,notify=True)
                            

                        #pprint(comment)
                if data_save:
                    save_to_json(parent_post_list,"parentPostList.json")


            for _ in range(NOTIFICATION_UPDATE_INTERVEL):
                time.sleep(1)
                if app_close: 
                    return
        except Exception as e:
            print(e)
            time.sleep(1)


notificationListener()

    
