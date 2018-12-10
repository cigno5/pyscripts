import argparse
import json
from datetime import datetime, timedelta

import requests

import _common


def export():
    base_url = "https://www.icscards.nl"
    login_url = "%s/pub/nl/pub/login" % base_url
    transactions_url = \
        "{baseurl}/sec/nl/sec/transactions/search?fromDate={start_date}&untilDate={end_date}&accountNumber={account}" \
            .format(baseurl=base_url,
                    start_date=from_date.strftime("%Y-%m-%d"),
                    end_date=to_date.strftime("%Y-%m-%d"),
                    account=account)

    s = requests.Session()
    s.get(base_url)

    # logging in
    s.post(login_url, json={"loginType": "PASSWORD",
                            "virtualPortal": "ICS-ABNAMRO",
                            "username": username,
                            "password": password})
    # extract header
    more_headers = {
        'X-XSRF-TOKEN': s.cookies.get('XSRF-TOKEN')
    }

    r = s.get(transactions_url, headers=more_headers)
    return json.loads(r.text)


def load_settings():
    try:
        _settings = dict(_common.load_configuration(args.config or 'icsexport.ini')['icscards'])
    except _common.ConfigFileError:
        _settings = {}

    if args.username:
        _settings['username'] = args.username

    if args.password:
        _settings['password'] = args.password

    if args.account:
        _settings['account'] = args.account

    for k in ['username', 'password', 'account']:
        if k not in _settings:
            raise ValueError("Missing '%s' settings " % k)

    if args.from_date:
        _from = datetime.strptime(args.from_date, "%d%m%Y")
    else:
        _from = (datetime.now() - timedelta(days=1)).replace(day=1)

    if args.to_date:
        _to = datetime.strptime(args.to_date, "%d%m%Y")
    else:
        _to = datetime.now()

    return _settings['username'], _settings['password'], _settings['account'], _from, _to


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", help="Username")
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-a", "--account", help="Account number")
    parser.add_argument('-c', "--config",
                        help="The exporter configuration file. Parameters -u,-p and -a will override this settings"
                             "If not specified a file 'icsexport.ini' will be searched in $HOME, "
                             "$HOME/.config/ or $PYSCRIPTS_CONFIG environment variables")

    parser.add_argument("--from-date", help="From date in format ddmmyyyy (default: beginning of the month)")
    parser.add_argument("--to-date", help="To date in format ddmmyyyy (default: today)")

    args = parser.parse_args()

    username, password, account, from_date, to_date = load_settings()

    transaction_list = export()
    for transaction in transaction_list:
        print(transaction)
