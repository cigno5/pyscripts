import argparse
import getpass
import json
import os
import re
import sys
from datetime import datetime, timedelta

import requests

import abnconv
from abnconv import QIFOutput, Trsx


def extract_transactions():
    base_url = "https://www.icscards.nl"
    login_url = "%s/pub/nl/pub/login" % base_url
    account_url = "%s/sec/nl/sec/allaccountsv2" % base_url
    transactions_url = \
        "{baseurl}/sec/nl/sec/transactions/search?fromDate={start_date}&untilDate={end_date}&accountNumber=" \
            .format(baseurl=base_url,
                    start_date=from_date.strftime("%Y-%m-%d"),
                    end_date=to_date.strftime("%Y-%m-%d"), )

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

    r = s.get(account_url, headers=more_headers)
    if not r.ok:
        raise ValueError

    all_transactions = list()
    for account_data in [ad for ad in json.loads(r.text) if ad['valid'] is True]:
        account_number = str(account_data['accountNumber'])
        r = s.get(transactions_url + account_number, headers=more_headers)
        account_transactions = json.loads(r.text)
        for account_transaction in account_transactions:
            account_transaction['accountNumber'] = account_number
            all_transactions.append(account_transaction)

    return all_transactions


def read_transactions():
    all_lines = ''
    for line in sys.stdin:
        if line == 'end\n':
            break
        else:
            all_lines += line

    account_transactions = json.loads(all_lines)

    all_transactions = list()
    for account_transaction in account_transactions:
        account_transaction['accountNumber'] = '65770350018'
        all_transactions.append(account_transaction)

    return all_transactions


def load_settings():
    if args.password:
        _password = args.password
    else:
        _password = getpass.getpass(prompt='Please input your password')

    if args.from_date:
        try:
            _from = datetime.strptime(args.from_date, "%d%m%Y")
        except ValueError:
            _from = datetime.now() - timedelta(days=abs(int(args.from_date)))
    else:
        _from = (datetime.now() - timedelta(days=1)).replace(day=1)

    if args.to_date:
        _to = datetime.strptime(args.to_date, "%d%m%Y")
    else:
        _to = datetime.now()

    if args.file:
        _file = args.file
    else:
        _file = os.path.join(os.getcwd(), "transactions_%s-%s.qif" % (
            _from.strftime("%d%m%Y"), _to.strftime("%d%m%Y")
        ))

    return args.username, _password, _from, _to, _file


def export_transactions():
    payee_re = re.compile("((www.)?[\w\.]+).+")

    with QIFOutput(file) as out:
        for transaction in transactions:
            if transaction['transactionDate'] is None \
                    or transaction['description'] == '' \
                    or transaction['typeOfTransaction'] == 'A':
                continue

            account = abnconv.find_account(transaction['accountNumber'])
            description = transaction['description']

            tsx = Trsx(account.iban)
            tsx.type = 'Bank'
            tsx.memo = description

            tsx.date = datetime.strptime(transaction['transactionDate'], '%Y-%m-%d')
            tsx.amount = float(transaction['billingAmount']) * -1

            tsx.payee = payee_re.search(description).group(1)

            if transaction['typeOfTransaction'] == 'P':
                tsx.dest_iban = account.ics_debit_iban
                tsx.payee = None
                tsx.date -= timedelta(days=1)

            out += tsx


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("username", help="Username")
    parser.add_argument("-p", "--password", help="Password, if not specified it will be requested")
    parser.add_argument("-c", "--config", help="Abnconv.ini configuration file (as for abnconv script)")

    parser.add_argument("--from-date", help="From date in format ddmmyyyy (default: beginning of the month) "
                                            "or -d (days)")
    parser.add_argument("--to-date", help="To date in format ddmmyyyy (default: today)")

    parser.add_argument("--file", help="Output file (default will be created using dates)")

    parser.add_argument("--read", action='store_true', help="Read transactions from stdin (such a shame!)")

    args = parser.parse_args()

    abnconv.accounts = abnconv.load_accounts(args.config or 'abnconv.ini')

    username, password, from_date, to_date, file = load_settings()

    if args.read:
        print("Read transactions from stdin, to close type 'end' and hit enter")
        transactions = read_transactions()
    else:
        print("Extract transactions from %s to %a" % (from_date.strftime("%d/%m/%Y"), to_date.strftime("%d/%m/%Y")))
        transactions = extract_transactions()

    if len(transactions) > 0:
        export_transactions()
    else:
        print("No transaction found in the specified period")
