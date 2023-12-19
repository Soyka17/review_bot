from datetime import datetime, timedelta
import requests
import random
import json
import sys

# INV LINK: http://localhost:8065/signup_user_complete/?id=

BOT_USERNAME = "ReviewBot"
BOT_PASSWORD = "1234567890"
CHANNEL_NAME = "reviews"
URL = "http://localhost:8065/api/v4/"

PLUS_WORKER_REACTION = "heavy_plus_sign"
COMMENT_WORKER_REACTION = "speech_balloon"
DONE_TASK_REACTION = "white_check_mark"

WORKERS_LIST = ["Yanka", "Yanochka", "Kotyatka", "Kotenka", "Solnce", "Kotenbka", "Yanya"]


def login(login, password):
    ret = dict()
    resp = requests.post(URL + 'users/login',
                         data='{"login_id":"' + login + '","password":"' + password + '"}')
    if resp.status_code != 200:
        print("Ошибка авторизации: проверьте логин и пароль бота")
        sys.exit()

    bot_info = json.loads(resp.text)
    ret["token"] = resp.headers["Token"]
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


def get_border_date():
    return datetime.now() - timedelta(days=1)


def get_workdays():
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
        if is_message_task(i["message"]):
            ret.append(i)

    return ret


def is_message_task(message):
    """
    формат сообщения-таски:
        DSGN-1234 "Двигать пикселс" by Яночка
    возращает bool, message -> dict("id", "description", "post_id", "assign_to")
    """

    TASK_PREFIX = "DSGN-"
    DESCRIPTION_PREFIX = ' "'
    ASSIGN_TO_PREFIX = "by "

    return not (TASK_PREFIX not in message or DESCRIPTION_PREFIX not in message or ASSIGN_TO_PREFIX not in message)


def get_workers_from_messages(messages, bot_id):
    """
    формат сообщения-объявления дежурного
    Дежурные на сегодня: @Yana, @Yanochka, @Yanka
    """
    WORKERS_PREFIX = "Дежурные на сегодня: "

    for msg in messages:
        if WORKERS_PREFIX in msg["message"] and msg["user_id"] == bot_id:
            curr = msg["message"]
            curr = curr.replace(WORKERS_PREFIX, "").replace("@", "").split(", ")
            return curr
    return


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
            if len(curr_msg) == 0 or len(curr_msg[PLUS_WORKER_REACTION]) == 0 or w not in curr_msg[PLUS_WORKER_REACTION]:
                ret[w].append(msg_id)

    return ret


def send_messages_in_intersect(tasks, all_messages, text):
    match = False
    for msg in all_messages:
        if msg["id"] in tasks:
            text += msg["message"] + "\n"
            match = True

    text = text.replace("by ", "by @")
    if match:
        send_message(CHANNEL_NAME, text, bot["id"])
    return


def send_debt_messages(debt, all_messages, workers_info):
    text = "Долги дежурных: \n"
    match = False
    for worker in debt:
        if len(debt[worker]) == 0:
            continue
        match = True
        text += f"@{workers_info[worker]}:"
        for task in debt[worker]:
            for msg in all_messages:
                if msg["id"] == task:
                    text += f"{msg['message']}, "
        text += "\n\n"
    text = text.replace("by ", "by @")
    if match:
        send_message(CHANNEL_NAME, text, bot["token"])
    return


def send_workers_message():
    text = "Дежурные на сегодня: "
    workers = random.sample(WORKERS_LIST, 3)
    for w in workers:
        text += f"@{w}, "
    send_message(CHANNEL_NAME, text, bot['token'])


def send_message(channel, message, token):
    payload = {
        "channel_id": channel,
        "message": message
    }

    resp = requests.post(URL + "posts", json=payload, headers=auth(token))


bot = login(BOT_USERNAME, BOT_PASSWORD)

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

for curr_messages in filtered:
    curr_tasks = get_task_messages(curr_messages)

    curr_workers = get_workers_from_messages(curr_messages, bot["id"])
    if curr_workers is None or len(curr_workers) == 0 and len(curr_tasks[0]) != 0:
        continue

    curr_workers = set(curr_workers)
    curr_workers_with_id = get_workers_ids(curr_workers, bot["token"])
    for w in curr_workers_with_id:
        workers_info[curr_workers_with_id[w]] = w

    messages_with_reactions = dict()
    for t in curr_tasks:
        messages_with_reactions[t["id"]] = get_tasks_reactions(t, bot["token"])

    curr_done_tasks = get_three_plus_tasks(messages_with_reactions, curr_workers_with_id.values())
    curr_comm_tasks = get_commented_tasks(messages_with_reactions, curr_workers_with_id.values())
    curr_debt_tasks = get_workers_debt(messages_with_reactions, curr_workers_with_id.values())

    for i in curr_done_tasks:
        done_tasks.append(i)

    for i in curr_comm_tasks:
        comm_tasks.append(i)

    for i in curr_debt_tasks:
        if i not in debt_tasks:
            debt_tasks[i] = list()
        for j in curr_debt_tasks[i]:
            debt_tasks[i].append(j)

send_messages_in_intersect(done_tasks, all_messages, "Можно закрывать: ")
send_messages_in_intersect(comm_tasks, all_messages, "Проверить комментарии: ")
send_debt_messages(debt_tasks, all_messages, workers_info)
send_workers_message()
