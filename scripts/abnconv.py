from __future__ import absolute_import, print_function

import argparse
import collections
import datetime
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree
import zipfile

import _common

Account = collections.namedtuple('Account', 'iban,name,ics_account,ics_debit_iban')

ns = {'xmlns': "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}

BEA_re = re.compile("(?P<subtype>[GB])EA, (Betaalpas|Google Pay)\s+(?P<payee>.+),(?P<pas>PAS\d+)\s+(?P<code>NR:[\w\d]+),?\s+(?P<datetime>[\d\.]{8}\/[\d\.:]{5})\s+(?P<place>.+)")

SEPA_re = re.compile("(/(TRTP|RTYP)/|^SEPA).+")
SEPA_markers_re = re.compile("/(?P<field>\w+)/(?P<value>.+?)(?=(/|$))")
SEPA_markers2_re = re.compile("(?P<field>\w+):\s(?P<value>.+?)(?=(\s+\w+:|$))")

ABN_re = re.compile("(?P<payee>ABN AMRO Bank N.V.)\s+(?P<memo>\w+).+")

SPAREN_re = re.compile("ACCOUNT BALANCED\s+(?P<memo>CREDIT INTEREST.+)For interest rates")

STORTING_re = re.compile("STORTING\s+.+,PAS (\d+)")

TIKKIE_re = re.compile("/REMI/(?P<memo>(?P<id>Tikkie ID \d+),\s*(?P<info>.+?),\s*Van\s+(?P<payee>.+?),\s*(?P<iban>\w\w\d\d[\w\d]{4}\d{10,}))")

SUPPORTED_TRANSACTIONS = {
    'tikkie': TIKKIE_re,
    'bea': BEA_re,
    'sepa': SEPA_re,
    'abn': ABN_re,
    'sparen': SPAREN_re,
    'storting': STORTING_re,
}

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


class Trsx:
    def __init__(self, account_iban):
        self.source_iban = account_iban
        self.dest_iban = None
        self.type = None
        self.date = None
        self.amount = None
        self.payee = None
        self.memo = None
        self.kenmerk = None

    def __eq__(self, other):
        if type(other) == Trsx:
            return self.source_iban == other.source_iban \
                   and self.dest_iban == other.dest_iban \
                   and self.type == other.type \
                   and self.date == other.date \
                   and self.amount == other.amount \
                   and self.payee == other.payee \
                   and self.memo == other.memo \
                   and self.kenmerk == other.kenmerk
        else:
            return False

    def __hash__(self):
        return hash("%s-%s-%s-%s-%s/%s" %
                    (self.source_iban,
                     self.dest_iban,
                     self.date.strftime("%Y%m%d"),
                     str(self.amount),
                     self.kenmerk,
                     self.memo))

    def __str__(self):
        return "{dt}: {src} -> {dst} {amt} ({pay}: {memo} {kenmerk})".format(dt=self.date.strftime("%d/%m/%Y"),
                                                                             src=self.source_iban,
                                                                             dst=self.dest_iban,
                                                                             amt=self.amount,
                                                                             pay=self.payee,
                                                                             memo=self.memo,
                                                                             kenmerk=self.kenmerk)

    def is_transfer_transaction(self):
        return self.dest_iban in accounts

    def complementary(self):
        if not self.is_transfer_transaction():
            raise ValueError("Complementary Trsx available only for transfer transactions")

        compl = Trsx(self.dest_iban)
        compl.dest_iban = self.source_iban
        compl.type = self.type
        compl.date = self.date
        compl.amount = self.amount * -1
        compl.payee = self.payee
        compl.memo = self.memo
        compl.kenmerk = self.kenmerk
        return compl

    def get_qif_tx(self):
        def nn(v):
            return v if v else ''

        var = {
            'type': self.type,
            'date': self.date.strftime("%Y/%m/%d"),
            'amount': self.amount,
            'payee': nn(self.payee),
            'memo': "{0}{1}".format(nn(self.memo), (' (' + self.kenmerk + ')' if self.kenmerk else '')),
            'ledger': '',
        }

        if self.is_transfer_transaction():
            if self.memo is None:
                var['memo'] = 'Transfer'

            var['ledger'] = '[%s]' % _get_account_name(self.dest_iban)

        return qif_tpl_plain_tsx.format(**var)


def _get_account_name(iban):
    return accounts[iban].name


def process_entry(account_iban, elem):
    def find_sepa_field(field, field_mk2):
        if SEPA_re.search(transaction_info):
            fields = {x[0]: x[1]
                      for x in
                      SEPA_markers_re.findall(transaction_info) + SEPA_markers2_re.findall(transaction_info)}
            if field in fields:
                return fields.get(field)
            elif field_mk2 in fields:
                return fields.get(field_mk2)

        return None

    def _get_regex():
        for _type, regexp in SUPPORTED_TRANSACTIONS.items():
            _match = regexp.search(transaction_info)
            if _match:
                return _type, _match

        return None, None

    tsx = Trsx(account_iban)

    tsx.date = datetime.datetime.strptime(elem.find("xmlns:ValDt/xmlns:Dt", namespaces=ns).text, "%Y-%m-%d")
    tsx.amount = float(elem.find("xmlns:Amt", namespaces=ns).text)
    if elem.find("xmlns:CdtDbtInd", namespaces=ns).text == 'DBIT':
        tsx.amount *= -1

    transaction_info = elem.find("xmlns:AddtlNtryInf", namespaces=ns).text

    tx_type, match = _get_regex()

    if tx_type == 'bea':
        tsx.type = 'Bank' if match.group("subtype") == 'B' else 'Cash'
        tsx.payee = match.group("payee")
        tsx.memo = transaction_info
        _xxx = elem.find("xmlns:AcctSvcrRef", namespaces=ns)
        tsx.kenmerk = _xxx.text if _xxx else None

    elif tx_type == 'sepa':
        tsx.type = 'Bank'
        tsx.payee = find_sepa_field('NAME', 'Naam')
        tsx.memo = find_sepa_field("REMI", 'Omschrijving')
        tsx.kenmerk = find_sepa_field('MARF', 'Kenmerk')
        tsx.dest_iban = find_sepa_field('IBAN', 'IBAN')

    elif tx_type == 'tikkie':
        tsx.type = 'Bank'
        tsx.payee = match.group("payee")
        tsx.memo = match.group("memo")
        tsx.dest_iban = match.group('iban')

    elif tx_type == 'abn':
        tsx.type = 'Bank'
        tsx.payee = match.group("payee")
        tsx.memo = match.group("memo")

    elif tx_type == 'sparen':
        tsx.type = 'Bank'
        tsx.payee = "ABN AMRO Bank N.V."
        tsx.memo = match.group("memo")

    elif tx_type == 'storting':
        tsx.type = 'Cash'
        tsx.payee = 'Unknwon'
        tsx.memo = None
    else:
        tsx.type = 'Bank'
        tsx.payee = 'Unknwon'
        tsx.memo = transaction_info

    return tsx


def _qif_account(account_name, account_type):
    return qif_account_tpl.format(name=account_name, type=account_type)


def _trsx_list(file):
    xml_parser = xml.etree.ElementTree.XMLParser(encoding='cp1252')

    def n(name):
        return "{urn:iso:std:iso:20022:tech:xsd:camt.053.001.02}" + name

    if file[-3:] == 'xml':
        tree = xml.etree.ElementTree.parse(file, xml_parser)

        account_iban = tree.find('xmlns:BkToCstmrStmt/xmlns:Stmt/xmlns:Acct/xmlns:Id/xmlns:IBAN', namespaces=ns).text
        for elem in tree.iter(tag=n("Ntry")):
            trsx = process_entry(account_iban, elem)
            if trsx:
                yield trsx
                # complementary transaction is not needed anymore, homebank is able to spot it by its own
                # if trsx.is_transfer_transaction():
                #     yield trsx.complementary()
    else:
        raise ValueError('Only CAM.53 XML files are supported')


def _all_files():
    def cleanup_file():
        _tmp_file = os.path.join(tmp_dir, 'tmp_clean')
        with open(_tmp_file, 'w') as tmp_clean:
            with open(_file, 'r') as dirty_file:
                for l in dirty_file.readlines():
                    tmp_clean.write(l.replace('\x00', ''))
        os.remove(_file)
        os.rename(_tmp_file, _file)

    for source in args.source:
        if zipfile.is_zipfile(source):
            tmp_dir = tempfile.mkdtemp(prefix="abnconv_")
            with zipfile.ZipFile(source, 'r') as zf:
                zf.extractall(tmp_dir)

            for _file in [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)]:
                cleanup_file()
                yield _file

            shutil.rmtree(tmp_dir)
            if args.prune:
                os.remove(source)
        elif os.path.isfile(source) and source[-3:] == 'xml':
            yield source
            if args.prune:
                os.remove(source)


class QIFOutput:
    def __init__(self, output_path):
        self.output_path = output_path
        self.output_file = None
        self.accounts = {}
        self._transaction_list = set()
        self.added = 0
        self.skipped = 0

    def __enter__(self):
        self.output_file = open(self.output_path, 'w')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for qif_entry_list in self.accounts.values():
            for qif_entry in qif_entry_list:
                print(qif_entry, file=self.output_file)

        self.output_file.close()

    def __iadd__(self, transaction: Trsx):
        if transaction not in self._transaction_list:
            self._get_list(transaction.source_iban).append(transaction.get_qif_tx())
            self._transaction_list.add(transaction)
            self.added += 1
        else:
            if 'args' in vars() and args.verbose:
                print("Found duplicated transaction: %s" % transaction)
            self.skipped += 1

        return self

    def _get_list(self, account):
        if account not in self.accounts:
            self.accounts[account] = list()
            self.accounts[account].append(qif_account_tpl.format(name=_get_account_name(account), type='Bank'))
        return self.accounts[account]


def find_account(ics_account):
    for account in accounts.values():
        if account.ics_account and account.ics_account == ics_account:
            return account


def load_accounts(conf_file):
    conf_parser = _common.load_configuration(conf_file)
    _accounts = {}
    for account_conf in [conf_parser[section] for section in conf_parser.sections()]:
        iban = account_conf['iban']
        name = account_conf.get('name', iban)
        ics_account = account_conf.get('ics_account', None)
        ics_debit_iban = account_conf.get('ics_debit_iban', None)
        _accounts[iban] = Account(iban, name, ics_account, ics_debit_iban)

    return _accounts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="+", help="ABN AMRO CAMT export file")
    parser.add_argument("--output", help="QIF output file")
    parser.add_argument("--verbose", action='store_true')
    parser.add_argument("--prune", action='store_true', help='Delete original files when conversion is done')
    parser.add_argument('-c', "--config", help="The accounts configuration file. "
                                               "If not specified a file 'abnconv.ini' will be searched in $HOME, "
                                               "$HOME/.config/ or $PYSCRIPTS_CONFIG environment variables")

    args = parser.parse_args()

    accounts = load_accounts(args.config or 'abnconv.ini')

    out_path = args.output if args.output else args.source[0] + '.qif'
    with QIFOutput(out_path) as out:
        for source_file in _all_files():
            for _trsx in _trsx_list(source_file):
                out += _trsx

    print("""
Process completed:
    {inserted} transactions inserted
    into {accounts} accounts
    and {dup} transactions reported as duplicated""".format(inserted=out.added,
                                                            accounts=len(out.accounts),
                                                            dup=out.skipped))
