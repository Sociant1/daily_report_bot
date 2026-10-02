import os, json, datetime, requests, discord
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request
import json

flaskapp = Flask(__name__)

dT = os.getenv("DISCORD_TOKEN")
tT = os.getenv("TOGGL_TOKEN")

textID = 1549388013581242450
reportsID = 1549443785925197924

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents
)

reminder = datetime.time(
    hour=7,
    minute=00,
    tzinfo=ZoneInfo("Europe/Stockholm")
)

@tasks.loop(time=reminder)
async def morning_reminder():
    channel = bot.get_channel(textID)
    if channel:
        await channel.send("Good morning! Are you ready for your daily report?")
    else:
        print(f"Error: channel ID '{channel}' not found.")

states = {}

@flaskapp.route("/workouts", methods=["POST"])
def workouts():
    data = request.get_json()

    workoutList = data["workouts"].split('\n')
    workoutList = [json.loads(workout) for workout in workoutList]

    for workout in workoutList:
        if workout["distance"]:
            workout["distance"] = workout["distance"].replace(',', '').replace(' m', '').strip()
            workout["distance"] = int(workout["distance"])
        if workout["duration"]:
            workout["duration"] = workout["duration"].replace(',', '').replace(' sec', '').strip()
            workout["duration"] = int(workout["duration"])

    with open("daily_report_bot/workouts.json", "w") as fw:
        json.dump(workoutList, fw, indent=4)

    return "Workout data saved", 200


if __name__ == "__main__":
    flaskapp.run(host="0.0.0.0", port=5001)

@bot.event
async def on_ready():
    print("BOT READY")
    if not morning_reminder.is_running():
        morning_reminder.start()

@bot.command()
async def report(ctx):
    today = datetime.date.today()

    report = {
        "yesterday" : [],
        "meals" : [],
        "exercises" : [],
        "problems" : {
            "had_problem" : False,
        },
        "daily_goal" : None,
        "entries" : [],
    }

    states[ctx.author] = {
        "state" : 'yesterday',
        "date" : today,
        "report" : report
    }

    yesterday = today - datetime.timedelta(days=1)
    start, end = yesterday.isoformat(), today.isoformat()
    apiParams = {
        "start_date" : start,
        "end_date" : end
    }
    response = requests.get(
        url="https://api.track.toggl.com/api/v9/me/time_entries",
        auth=(tT, "api_token"),
        params=apiParams
    )
    response = response.json()

    for entry in response:
        time = entry["duration"]
        hours = time // 3600
        minutes = (time % 3600) // 60
        seconds = time % 60

        project = requests.get(
            url=f'https://api.track.toggl.com/api/v9/workspaces/{entry["workspace_id"]}/projects/{entry["project_id"]}',
            auth=(tT, "api_token"),
            ).json()
        task = (f'- [{project["name"]}] {entry["description"]} | {hours}h {minutes}m {seconds}s')
        states[ctx.author]["report"]["entries"].append(task)

    await ctx.channel.send("What did you work on yesterday?")

@bot.event
async def on_message(msg):
    if msg.author == bot.user:
        return

    if msg.content.startswith("!"):
        await bot.process_commands(msg)
        return

    if msg.author in states:
        state = states[msg.author]["state"]
        report_date = states[msg.author]["date"]
        report = states[msg.author]["report"]

        if state == 'yesterday':
            message = msg.content.split('\n')
            report["yesterday"] = message

            await msg.channel.send("What did you eat yesterday?")
            states[msg.author]["state"] = 'meals'
            return

        if state == 'meals':
            message = msg.content.split('\n')
            report["meals"] = message

            await msg.channel.send("Did you do any strength training? (y/n)")
            states[msg.author]["state"] = 'question1'
            return

        if state == 'question1':
            message = msg.content.strip().lower()

            if message == "y":
                await msg.channel.send("What exercises did you do?")
                states[msg.author]["state"] = 'exercised'
                return

            elif message == "n":
                await msg.channel.send("Did you run into any problems? (y/n)")
                states[msg.author]["state"] = 'question2'
                return
            else:
                await msg.channel.send('Please answer with "y" or "n".')

        if state == 'exercised':
            message = msg.content.split('\n')
            report["exercises"] = message

            await msg.channel.send("Did you run into any problems? (y/n)")
            states[msg.author]["state"] = 'question2'
            return

        if state == 'question2':
            message = msg.content.strip().lower()

            if message == "y":
                report["problems"]["had_problem"] = True

                await msg.channel.send("What problem did you run into?")
                states[msg.author]["state"] = 'problem'
                return
            elif message == "n":
                report["problems"]["had_problem"] = False 

                await msg.channel.send("What is your goal for today?")
                states[msg.author]["state"] = 'daily_goal'
                return
            else:
                await msg.channel.send('Please answer with "y" or "n"')
                return

        if state == 'problem':
            report["problems"]["problem"] = msg.content

            await msg.channel.send("How did you solve the problem?")
            states[msg.author]["state"] = 'solution'
            return

        if state == 'solution':
            report["problems"]["solution"] = msg.content

            await msg.channel.send("What is your goal for today?")
            states[msg.author]["state"] = 'daily_goal'
            return

        if state == 'daily_goal':
            report["daily_goal"] = msg.content

            path = f'daily_report_bot/{msg.author}.json'
            if os.path.exists(path):
                with open(path, "r") as fr:
                    try:
                        content = json.load(fr)
                    except json.JSONDecodeError:
                        content = {}
            else:
                content = {}

            content[report_date.isoformat()] = report
            with open(path, "w") as fw:
                json.dump(content, fw, indent=4)

            message = f'```DAILY REPORT [{report_date}]\n\nYesterday\n'
            for row in report["yesterday"]:
                message += f'{row}\n'
            message += '\nMEALS '
            for i in report["meals"]:
                message += f'| {i} '
            message += '\n\n'
            if report["exercises"]:
                message += 'Strength Training\n'
                for row in report["exercises"]:
                    message += f'{row}\n'
            message += 'Projects\n'
            for entry in report["entries"]:
                message += f'{entry}\n'
            if report["problems"]["had_problem"] == True:
                message += f'Problem: {report["problems"]["problem"]}\n'
                message += f'Solution: {report["problems"]["solution"]}\n'
            message += f'\nDAILY GOAL: {report["daily_goal"]}```'

            channel = bot.get_channel(reportsID)
            if channel:
                await channel.send(message)
            else:
                print(f"Error: channel ID '{channel}' not found.")

            del states[msg.author]
            return        

bot.run(dT)