# deso-comment-checker
# Introduction
Python script to 
This script uses deso_sdk.py from https://github.com/deso-protocol/deso-python-sdk

# Attention
For this script you need the seed hex of the account you want to post the reply with the answer. Handle with care. Use this code at your own risk. Better create a seperate account with less amount just for the post fees.

## Features


# Install required libraries
Needs Python3

`python -m venv myenv`

Linux:

`source myenv/bin/activate`

Windows:

`myenv\Scripts\activate.bat`

To install required libraries

`pip install -r requirements.txt`


# Run the app
`python deso-comment-checker.py`

---

Use the following format when writing the post.

`@commentchecker on` To monitor and notify you for any changes in the entire thread 

Just putting `@commentchecker` also will turn on that thread(may change in future)

`@commentchecker off` To delete registered post thread 

`@commentchecker off all` To remove all posts threads notifications 

`@commentchecker info` To check registered posts threads 
