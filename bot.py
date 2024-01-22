from datetime import datetime, timedelta
import requests
import re
import json
import sys

URL = "http://localhost:8065/api/v4/"

BOT_USERNAME = "ReviewBot"
BOT_PASSWORD = "1234567890"
BOT_TOKEN = ""                  # Можно оставить пустым, бот попробует запросить его сам

CHANNEL_NAME = "reviews"
CHANNEL_ID = ""                 # Можно оставить пустым, бот выберет первый канал с CHANNEL_NAME

PLUS_WORKER_REACTION = "heavy_plus_sign"
COMMENT_WORKER_REACTION = "speech_balloon"
DONE_TASK_REACTION = "white_check_mark"

WORKERS_LIST = [
    ["name_01", "name_02", "name_03"],  # Понедельник
    ["name_04", "name_05", "name_06"],  # Вторник
    ["name_07", "name_08", "name_09"],  # Среда
    ["name_10", "name_11", "name_12"],  # Четверг
    ["name_13", "name_14", "name_15"],  # Пятница
]

TASKS_PREFIXES = ["DSGN"]

DEBT_TEXT = "проверьте задачу и поставьте соответствующую реакцию под сообщением"
COMMENT_TEXT = "проверьте комментарии к задаче"
DONE_TEXT = "поставьте реакцию \"done\" и закройте задачу по готовности"

TEST_BUIILD = False

def login(login, password):
    ret = dict()
    resp = requests.post(URL + 'users/login',
                         data='{"login_id":"' + login + '","password":"' + password + '"}')
    if resp.status_code != 200:
        print("Ошибка авторизации: проверьте логин и пароль бота")
        sys.exit()

    bot_info = json.loads(resp.text)
    ret["token"] = resp.headers["Token"]
    if BOT_TOKEN != "":
        ret["token"] = BOT_TOKEN
    ret["id"] = bot_info["id"]

    return ret


def auth(token):
    return {"Authorization": "Bearer " + token}


def get_channel_id(name, token):
    resp = requests.get(URL + 'channels', headers=auth(token))
    channels = json.loads(resp.text)

    for ch in channels:
        if ch["display_name"] == name:
            return ch["id"]

    return


def get_workdays():
    if TEST_BUIILD:
        return [
            [1705345200, 1705348800],
            [1705341600, 1705345200],
            [1705338000, 1705341600]
        ]

    ret = list()
    curr_day = datetime.now()

    while len(ret) < 3:
        curr_day = curr_day - timedelta(days=1)
        if curr_day.weekday() < 5:
            only_date = curr_day.date()
            left = datetime.combine(only_date, datetime.min.time())
            right = left + timedelta(days=1)
            ret.append([int(left.timestamp()), int(right.timestamp())])
    return ret


def get_all_messages_since(date, channel, token):
    resp = requests.get(URL + 'channels/' + channel + "/posts?since=" + str(date), headers=auth(token))
    all_messages = json.loads(resp.text)
    ret = list()
    for id, msg in all_messages["posts"].items():
        ret.append(msg)

    return ret


def filter_messages_by_days(messages, timestamps):
    """
    :param messages: список всех сообщений
    :param timestamps: список из список по 2 элемента, 3 таймстемпов начала и конца рабочих дней, отсортированных по убыванию TS
    :return: лист длиной 3 с сгрупированными сообщениями по рабочим дням
    """
    ret = list()
    for _ in timestamps:
        ret.append([])

    for msg in messages:
        curr_ts = msg["create_at"] // 1000
        for i in range(len(timestamps)):
            if timestamps[i][0] < curr_ts < timestamps[i][1]:
                ret[i].append(msg)

    return ret


def get_task_messages(messages):
    ret = list()

    for i in messages:
        if is_message_task(i):
            ret.append(i)

    return ret


def is_message_task(message):
    DESCRIPTION_PREFIX = ''
    ASSIGN_TO_PREFIX = "by "

    author_id = message["user_id"]
    if author_id == bot["id"]:
        return False

    msg_text = message["message"]
    for prefix in TASKS_PREFIXES:
        if prefix in msg_text and DESCRIPTION_PREFIX in msg_text and ASSIGN_TO_PREFIX:
            return True

    return False


def get_message_datetime(msg):
    timestamp = msg["create_at"] // 1000
    day = datetime.fromtimestamp(timestamp)
    return day


def get_workers(day):
    if TEST_BUIILD:
        workdays = get_workdays()
        for i in range(len(workdays)):
            if workdays[i][0] <= day.timestamp() <= workdays[i][1]:
                return WORKERS_LIST[i]

    week_day = day.weekday()
    if week_day < 5:
        return WORKERS_LIST[week_day]
    return None


def get_workers_ids(workers, token):
    data = list()
    for i in workers:
        data.append(i.lower())
    resp = requests.post(URL + "users/usernames", json=data, headers=auth(token))
    workers_info = json.loads(resp.text)

    ret = dict()
    for i in workers_info:
        ret[i["username"]] = i["id"]

    return ret


def get_tasks_reactions(message, token):
    ret = dict()
    resp = requests.get(URL + 'posts/' + str(message["id"]) + '/reactions', headers=auth(token))

    reactions = json.loads(resp.text)
    if reactions is None:
        return ret

    for i in reactions:
        curr_emoji, curr_id = i["emoji_name"], i["user_id"]
        if curr_emoji not in ret:
            ret[curr_emoji] = set()
        ret[curr_emoji].add(curr_id)

    return ret


def get_three_plus_tasks(messages_with_reactions, curr_workers):
    ret = list()

    for msg_id in messages_with_reactions:
        curr_msg = messages_with_reactions[msg_id]
        if PLUS_WORKER_REACTION not in curr_msg:
            continue

        count = 0
        for reactor in curr_msg[PLUS_WORKER_REACTION]:
            if reactor in curr_workers:
                count += 1

        if count == 3:
            ret.append(msg_id)

    return ret


def get_commented_tasks(messages_with_reactions, curr_workers):
    ret = list()

    for msg_id in messages_with_reactions:
        curr_msg = messages_with_reactions[msg_id]
        if COMMENT_WORKER_REACTION not in curr_msg:
            continue

        for worker in curr_workers:
            if worker in curr_msg[COMMENT_WORKER_REACTION]:
                ret.append(msg_id)

    return ret


def get_workers_debt(messages_with_reactions, curr_workers):
    ret = dict()
    for w in curr_workers:
        ret[w] = list()

    for msg_id in messages_with_reactions:
        curr_msg = messages_with_reactions[msg_id]
        count = 0
        for w in curr_workers:
            if PLUS_WORKER_REACTION not in curr_msg or len(curr_msg) == 0 or len(curr_msg[PLUS_WORKER_REACTION]) == 0 or w not in curr_msg[PLUS_WORKER_REACTION]:
                ret[w].append(msg_id)

    return ret


def get_list_user_channel(channel_id, token):
    list_user = []
    req_users = requests.get(URL + 'channels/' + channel_id + '/members', headers=auth(token))
    users = json.loads(req_users.text)
    for i in users:
        list_user.append(i['user_id'])
    return list_user


def get_user_info(users_id, token):
    users_info = []
    for user in users_id:
        req_user_name = requests.get(URL + 'users/' + user, headers=auth(token))
        user_name = json.loads(req_user_name.text)
        users_info.append(user_name)
    return users_info


def get_creator_task(mess, users_info):
  regex = re.findall(r'by \[(\D+)\]', mess)
  if len(regex) == 0:
      return None
  username = regex[0].split()
  for user in users_info:
    if username[0] in user['last_name'] and username[1] in user['first_name']:
      ret = user['username']
  return ret


def send_messages_in_intersect(channel_id, tasks, all_messages, text):
    if len(tasks) == 0:
        return

    for msg in all_messages:
        if msg["id"] in tasks:
            creator_task = get_creator_task(msg["message"], arr_user_info)
            text = f'@{creator_task} {text}'
            root_id = msg['id']
            send_thread_message(channel_id, text, root_id, bot["token"])
    return


def send_debt_messages(channel_id, debt, all_messages, workers_info):
    for worker in debt:
        if len(debt[worker]) == 0:
            continue

        for task in debt[worker]:
            for msg in all_messages:
                if msg["id"] == task:
                    text = f"@{workers_info[worker]} {DEBT_TEXT}"
                    root_id = msg['id']
                    send_thread_message(channel_id, text, root_id, bot["token"])
    return


def send_workers_message(channel_id, workers):
    text = "Дежурные на сегодня: "
    for w in workers:
        text += f"@{w}, "
    send_message(channel_id, text, bot['token'])


def send_message(channel, message, token):
    payload = {
        "channel_id": channel,
        "message": message
    }

    resp = requests.post(URL + "posts", json=payload, headers=auth(token))


def send_thread_message(channel, message, root_id, token):
    payload = {
        "channel_id": channel,
        "message": message,
        "root_id": root_id
    }

    resp = requests.post(URL + "posts", json=payload, headers=auth(token))


bot = login(BOT_USERNAME, BOT_PASSWORD)

review_channel_id = CHANNEL_ID
if CHANNEL_ID == "":
    review_channel_id = get_channel_id(CHANNEL_NAME, bot["token"])
    if not review_channel_id:
        print(f"Канал с именем {CHANNEL_NAME} не найден")
        sys.exit()

workdays = get_workdays()
all_messages = get_all_messages_since(workdays[2][0], review_channel_id, bot["token"])

filtered = filter_messages_by_days(all_messages, workdays)

done_tasks = list()
comm_tasks = list()
debt_tasks = dict()

workers_info = dict()

for curr_day_messages in filtered:
    if len(curr_day_messages) == 0:
        continue

    curr_day_tasks = get_task_messages(curr_day_messages)

    curr_day_workers = get_workers(get_message_datetime(curr_day_messages[0]))
    curr_day_workers = set(curr_day_workers)

    curr_day_workers_with_id = get_workers_ids(curr_day_workers, bot["token"])
    for w in curr_day_workers_with_id:
        workers_info[curr_day_workers_with_id[w]] = w

    messages_with_reactions = dict()
    for t in curr_day_tasks:
        messages_with_reactions[t["id"]] = get_tasks_reactions(t, bot["token"])

    curr_day_done_tasks = get_three_plus_tasks(messages_with_reactions, curr_day_workers_with_id.values())
    curr_day_comm_tasks = get_commented_tasks(messages_with_reactions, curr_day_workers_with_id.values())
    curr_day_debt_tasks = get_workers_debt(messages_with_reactions, curr_day_workers_with_id.values())

    for i in curr_day_done_tasks:
        done_tasks.append(i)

    for i in curr_day_comm_tasks:
        comm_tasks.append(i)

    for i in curr_day_debt_tasks:
        if i not in debt_tasks:
            debt_tasks[i] = list()
        for j in curr_day_debt_tasks[i]:
            debt_tasks[i].append(j)

list_users_id = get_list_user_channel(review_channel_id, bot["token"])
arr_user_info = get_user_info(list_users_id, bot["token"])
send_messages_in_intersect(review_channel_id, done_tasks, all_messages, DONE_TEXT)
send_messages_in_intersect(review_channel_id, comm_tasks, all_messages, COMMENT_TEXT)
send_debt_messages(review_channel_id, debt_tasks, all_messages, workers_info)
send_workers_message(review_channel_id, get_workers(datetime.now()))
