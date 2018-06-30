from __future__ import absolute_import, print_function

import argparse
import datetime
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ns = {'xmlns': "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}

BEA_re = re.compile("(?P<subtype>[GB])EA.+(\d{2}.){4}\d{2}(?P<payee>.+),PAS(\d+)")

SEPA_re = re.compile("/TRTP/.+")
SEPA_markers_re = re.compile("/(TRTP|CSID|NAME|MARF|REMI|IBAN|BIC|EREF)/")

ABN_re = re.compile("(?P<payee>ABN AMRO Bank N.V.)\s+(?P<memo>\w+).+")

SPAREN_re = re.compile("ACCOUNT BALANCED\s+(?P<memo>CREDIT INTEREST.+)For interest rates")

qif_account_tpl = """!Account
N{name}
T{type}
^"""

qif_tpl_plain_tsx = """!Type:{type}
D{date}
T{amount}
C
P{payee}
M{memo}
L{ledger}
^"""

qif_tpl_saving_tsx = "!Type:Bank\n" + qif_tpl_plain_tsx

qif_tpl_oth_tsx = "!Type:Oth A\n" + qif_tpl_plain_tsx


class Trsx:
    def __init__(self, account):
        self.account = account
        self.type = None
        self.date = None
        self.amount = None
        self.payee = None
        self.memo = None
        self.iban = None

    def is_saving_transaction(self):
        return self.iban == args.savings_iban

    def get_qif_tx(self, inverse=False):
        def nn(v):
            return v if v else ''

        var = {
            'type': self.type,
            'date': self.date.strftime("%Y/%m/%d"),
            'amount': self.amount,
            'payee': nn(self.payee),
            'memo': nn(self.memo),
            'ledger': '',
        }

        if self.is_saving_transaction():
            var['type'] = 'Oth A'
            var['ledger'] = '[%s]' % args.savings_iban
            if self.memo is None:
                var['memo'] = 'saving' if self.amount < 0 else 'withdrawal'

        if inverse:
            var['type'] = 'Oth A'
            var['amount'] *= -1
            var['ledger'] = '[%s]' % self.account

        return qif_tpl_plain_tsx.format(**var)


def process_entry(account, elem):
    def find_sepa_field(field):
        if SEPA_re.search(transaction_info):
            start = None
            for marker_match in SEPA_markers_re.finditer(transaction_info):
                if marker_match.group(1) == field:
                    start = marker_match.end(0)
                elif start:
                    return transaction_info[start:marker_match.start(0)]

        return None

    def _get_regex():
        for _type, regexp in {'bea': BEA_re, 'sepa': SEPA_re, 'abn': ABN_re, 'sparen': SPAREN_re}.items():
            _match = regexp.search(transaction_info)
            if _match:
                return _type, _match

        return None, None

    trsx = Trsx(account)

    trsx.date = datetime.datetime.strptime(elem.find("xmlns:ValDt/xmlns:Dt", namespaces=ns).text, "%Y-%m-%d")
    trsx.amount = float(elem.find("xmlns:Amt", namespaces=ns).text)
    if elem.find("xmlns:CdtDbtInd", namespaces=ns).text == 'DBIT':
        trsx.amount *= -1

    transaction_info = elem.find("xmlns:AddtlNtryInf", namespaces=ns).text

    tx_type, match = _get_regex()

    if tx_type == 'bea':
        trsx.type = 'Bank' if match.group("subtype") == 'B' else 'Cash'
        trsx.payee = match.group("payee")
        trsx.memo = transaction_info

    elif tx_type == 'sepa':
        trsx.type = 'Bank'
        trsx.payee = find_sepa_field('NAME')
        trsx.memo = find_sepa_field("REMI")
        trsx.iban = find_sepa_field('IBAN')

    elif tx_type == 'abn':
        trsx.type = 'Bank'
        trsx.payee = match.group("payee")
        trsx.memo = match.group("memo")

    elif tx_type == 'sparen':
        trsx.type = 'Bank'
        trsx.payee = "ABN AMRO Bank N.V."
        trsx.memo = match.group("memo")

    else:
        raise ValueError('Transaction type not supported for "%s"' % transaction_info)

    return trsx


def _qif_account(account_name, account_type):
    return qif_account_tpl.format(name=account_name, type=account_type)


def _trsxs(file):
    def n(name):
        return "{urn:iso:std:iso:20022:tech:xsd:camt.053.001.02}" + name

    if file[-3:] == 'xml':
        tree = ET.parse(file)

        account = tree.find('xmlns:BkToCstmrStmt/xmlns:Stmt/xmlns:Acct/xmlns:Id/xmlns:IBAN', namespaces=ns).text
        for elem in tree.iter(tag=n("Ntry")):
            trsx = process_entry(account, elem)
            if trsx:
                yield trsx
    else:
        raise ValueError('Only CAM.53 XML files are supported')


def _all_files():
    for source in args.source:
        if zipfile.is_zipfile(source):
            tmp_dir = tempfile.mkdtemp(prefix="abnconv_")
            with zipfile.ZipFile(source, 'r') as zf:
                zf.extractall(tmp_dir)

            for _file in [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)]:
                yield _file

            shutil.rmtree(tmp_dir)
        elif os.path.isfile(source) and source[-3:] == 'xml':
            yield source


class QIFOutput:
    def __init__(self, output_path):
        self.output_path = output_path
        self.output_file = None
        self.accounts = {}

    def __enter__(self):
        self.output_file = open(self.output_path, 'w')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for qif_entry_list in self.accounts.values():
            for qif_entry in qif_entry_list:
                print(qif_entry, file=self.output_file)

        self.output_file.close()

    def __iadd__(self, trsx: Trsx):
        account = trsx.account
        tsx_entries = self._get_list(account)

        tsx_entries.append(trsx.get_qif_tx())

        if trsx.is_saving_transaction():
            # for saving transactions a double entry has to be written to the output
            sav_entries = self._get_list(args.savings_iban, is_saving=True)
            sav_entries.append(trsx.get_qif_tx(inverse=True))

        return self

    def _get_list(self, account, is_saving=False):
        if account not in self.accounts:
            self.accounts[account] = list()
            self.accounts[account].append(qif_account_tpl.format(name=account,
                                                                 type="Oth A" if is_saving else "Bank"))
        return self.accounts[account]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="+", help="ABN AMRO CAMT export file")
    parser.add_argument("output", help="Output qif file")
    parser.add_argument('-s', "--savings-iban", help="The Savings IBAN to create internal transaction", default=None)

    args = parser.parse_args()

    entries = (e for f in _all_files() for e in _trsxs(f))

    with QIFOutput(args.output) as out:
        for e in entries:
            out += e
