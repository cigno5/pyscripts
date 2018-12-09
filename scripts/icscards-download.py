# https://www.icscards.nl/pub/nl/pub/login


import requests
import logging

# logging.basicConfig(level=logging.DEBUG)

s = requests.Session()
# session.headers = {
#     'Accept-Language': 'en-AU,en;q=0.9,it-IT;q=0.8,it;q=0.7,nl-NL;q=0.6,nl;q=0.5,en-GB;q=0.4,en-US;q=0.3',
#     'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.80 Safari/537.36',
#     'Content-Type': 'application/json;charset=UTF-8',
#     'Accept': 'application/json, text/plain, */*',
#     'Referer': 'https://www.icscards.nl/abnamrogb/login/login?URL=%2Fabnamrogb%2Fmijn%2Faccountoverview',
#     'Accept-Encoding': 'gzip, deflate, br',
#     'Connection': 'keep-alive',
#     'DNT': '1',
# }
import json


def prt(func):
    def xx(x):
        print("  cookies")
        for cookie in x.cookies:
            print("    " + str(cookie))
        print("  headers")
        for k, v in x.headers.items():
            print("    %s: %s" % (k, v))

    print("===================================================================================")
    print("Session")
    xx(s)

    r = func()
    print("Response")
    print(r.content)
    xx(r)


prt(lambda: s.get("https://www.icscards.nl/"))

payload = {"loginType": "PASSWORD",
           "virtualPortal": "ICS-ABNAMRO",
           "username": "xxxxxxxxxxx",
           "password": "xxxxxxxxxxx"}

prt(lambda: s.post("https://www.icscards.nl/pub/nl/pub/login", json=payload))

more_headers = {
    'X-XSRF-TOKEN': s.cookies.get('XSRF-TOKEN')
}

prt(lambda: s.get("https://www.icscards.nl/sec/nl/sec/transactions/search?fromDate=2018-11-26&untilDate=2018-12-09&accountNumber=xxxxxxxxxx", headers=more_headers))

#  b'{"timeStamp":"2018-12-09 21:30:04","errorCode":"T00001","id":"ZGPYAVEHYSGDOEB"}'
#  b'{"timeStamp":"2018-12-09 21:31:58","errorCode":"T00001","id":"ZVQBMQDQYTAXUTX"}'
