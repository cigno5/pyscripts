import xlrd
import argparse
import os
import functools


def find_best_options():
    assert os.path.exists(args.doodle_file), "Can't find doodle file at %s" % args.doodle_file
    # book = xlrd.open_workbook(args.doodle_file)
    # print("The number of worksheets is {0}".format(book.nsheets))
    # print("Worksheet name(s): {0}".format(book.sheet_names()))
    # sh = book.sheet_by_index(0)
    # print("{0} {1} {2}".format(sh.name, sh.nrows, sh.ncols))
    # print("Cell D30 is {0}".format(sh.cell_value(rowx=29, colx=3)))
    # for rx in range(sh.nrows):
    #     print(sh.row(rx))

    with xlrd.open_workbook(args.doodle_file) as wb:
        sheet = wb.sheet_by_index(0)

        title = sheet.cell_value(0, 0)
        poll_url = sheet.cell_value(1, 0)

        options = []
        people = []
        presences = [[] for _ in range(1, sheet.ncols)]

        for i, v in [(i, c.value) for i, c in enumerate(sheet.row(4))]:
            if i < 1:
                continue
            options.append("%s, %s" % (v, sheet.cell_value(5, i)))

        for r in range(6, sheet.nrows - 1):
            for c in range(sheet.ncols):
                value = sheet.cell_value(r, c)
                if c == 0:
                    person = value
                    people.append(person)
                    continue

                presences[c - 1].append(person if value == 'OK' else None)

    print(options)
    print(presences)

    # collect into groups
    def _c(_v):
        if type(_v) == int:
            _ret = _v
        elif _v is None:
            _ret = 0
        else:
            _ret = 1
        return _ret

    sorted_presences = sorted(presences, key=lambda pres: len([p for p in pres if p]), reverse=True)

    # grouping options by their presences
    count_group = {}
    for idx, option in enumerate(presences):
        count = functools.reduce(lambda x, y: _c(x) + _c(y), option)
        if count in count_group:
            count_group[count].append(idx)
        else:
            count_group[count] = [idx]

    print(count_group)

    for ref_opt_indexes in [v for _, v in sorted(count_group.items(), key=lambda it: it[0], reverse=True)]:
        print("group.......")
        for ref_opt_idx in ref_opt_indexes:
            ref_presences = set([p for p in presences[ref_opt_idx] if p])
            print("--------------------\nReference option: [%d] (count: %d) %s" % (ref_opt_idx, len(ref_presences), str(ref_presences)))

            for cmp_pres_idx, _cmp_presences in [(i, p) for i, p in enumerate(presences) if i != ref_opt_idx]:
                cmp_presences = set(p for p in _cmp_presences if p)
                print("  Compare with #%03d (%3d items): %s" % (cmp_pres_idx, len(cmp_presences), str(cmp_presences)))

                common_pref = cmp_presences.intersection(ref_presences)
                print("     %3d items in common.......: %s" % (len(common_pref), str(common_pref)))

                diff_pref = ref_presences.difference(cmp_presences)
                print("     %3d items left (ref)......: %s" % (len(diff_pref), str(diff_pref)))

                diff_pref = cmp_presences.difference(ref_presences)
                print("     %3d items left (cmp)......: %s" % (len(diff_pref), str(diff_pref)))

        break

if __name__ == '__main__':
    _cmds = {
        'best-option': find_best_options
    }

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    options_parser = subparsers.add_parser("best-options", help="Find the best dates with maximum people coverage")
    options_parser.set_defaults(command="best-option")
    options_parser.add_argument("doodle_file", help="Doodle xls export file")
    options_parser.add_argument('-n', '--options-number', type=int, default=2, help="Number of options to be chosen")

    args = parser.parse_args()

    _cmds[args.command]()
