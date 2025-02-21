import curses

buf = []


def handle_keypress(key):
    buf.append(key)
    if key == 27:
        return False
    else:
        return True


# def listen(window):
#     while True:
#         # key = window.getch()
#         key = window.getch()
#         # window.addstr(f'You pressed the "{key}" key!\n')
#         print(f'You pressed the "{key}" key!\n')
#         if key == 'q':
#             break
#         if not handle_keypress(key):
#             break


window = curses.initscr()
curses.curs_set(0)

while True:
    # key = window.getch()
    # key = window.get_wch()
    key = window.getkey()
    # window.addstr(f'You pressed the "{key}" key!\n')
    print(f'You pressed the "{key}" key!\n')
    if key == 'q':
        break
    if not handle_keypress(key):
        break

curses.curs_set(1)
print('by1')
# curses.def_prog_mode()
# curses.wrapper(listen)
