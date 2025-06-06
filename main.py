import discord
from discord.ext import commands, tasks
import os
import re
import random
import datetime
import asyncio
import database as db  # database.pyを読み込む
from flask import Flask
import threading

# --- 設定項目 ---
# 環境変数から設定を読み込む
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISBOARD_BOT_ID = 302050872383242240

# --- Botのプログラム ---

# Botに必要な権限（Intent）を設定
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

# Botのインスタンスを作成
bot = commands.Bot(command_prefix='/', intents=intents)

# 起動したときに1回だけ実行される処理
@bot.event
async def on_ready():
    # データベースの初期化（テーブルがなければ作る）
    await db.init_db()
    # リマインダータスクを開始
    if not reminder_task.is_running():
        reminder_task.start()
    # スラッシュコマンドをサーバーに登録（同期）
    await bot.tree.sync()
    # 起動メッセージをコンソール（Renderのログ）に表示
    print('------')
    print(f'{bot.user.name} が起動しました！')
    print('------')

# メッセージを受信したときに実行される処理
@bot.event
async def on_message(message):
    # 自分自身のメッセージは無視する
    if message.author == bot.user:
        return

    # メッセージの送信者がDisboardのBotか、埋め込みメッセージがあるかを確認
    if message.author.id == DISBOARD_BOT_ID and message.embeds:
        embed = message.embeds[0]
        # Bump成功メッセージかどうかを判定
        if embed.description and "表示順をアップしたよ" in embed.description:
            print("Bump成功メッセージを検知しました。")
            
            # Bumpしたユーザーを特定する
            match = re.search(r'<@!?(\d+)>', embed.description)
            if match:
                user_id = int(match.group(1))
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)

                if not user:
                    print(f"ユーザーID: {user_id} の情報が取得できませんでした。")
                    return
                
                count = await db.record_bump(user_id)
                print(f"{user.name} (ID: {user_id}) のBumpを記録しました。累計: {count}回")
                
                thanks_messages = [
                    f"ありがとう！サーバーが盛り上がるね！",
                    f"ナイスBump！君はヒーローだ！",
                    f"サンキュー！次も頼んだよ！",
                    f"お疲れ様！ゆっくり休んでね！"
                ]
                await message.channel.send(f"{user.mention} {random.choice(thanks_messages)} (累計 **{count}** 回)")

                if count in [10, 50, 100, 150, 200]:
                     await message.channel.send(f"🎉🎉Congratulation!!🎉🎉 {user.mention} なんと累計 **{count}回** のBumpを達成しました！本当にありがとう！")

                remind_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
                await db.set_reminder(message.channel.id, remind_time)
                print(f"次のリマインドを {remind_time.strftime('%Y-%m-%d %H:%M:%S UTC')} に設定しました。")

@bot.tree.command(name="bump_top", description="Bump回数のトップ5ランキングを表示します。")
async def bump_top(interaction: discord.Interaction):
    await interaction.response.defer()
    top_users = await db.get_top_users()
    
    if not top_users:
        await interaction.followup.send("まだ誰もBumpしていません。まずは`/bump`してみよう！")
        return

    embed = discord.Embed(title="🏆 Bumpランキング 🏆", color=discord.Color.gold())
    
    rank_text = ""
    for i, record in enumerate(top_users):
        try:
            user = await bot.fetch_user(record['user_id'])
            username = user.display_name
        except discord.NotFound:
            username = f"不明なユーザー (ID: {record['user_id']})"
        
        rank_text += f"**{i+1}位**: {username} - **{record['bump_count']}** 回\n"
    
    embed.description = rank_text
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="bump_user", description="指定したユーザーのBump回数を表示します。")
async def bump_user(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer()
    count = await db.get_user_count(user.id)
    await interaction.followup.send(f"{user.display_name}さんの累計Bump回数は **{count}回** です。")

@bot.tree.command(name="bump_time", description="次のBumpリマインド時刻を表示します。")
async def bump_time(interaction: discord.Interaction):
    await interaction.response.defer()
    reminder = await db.get_reminder()
    if reminder:
        remind_at = reminder['remind_at']
        await interaction.followup.send(f"次のBumpが可能になるのは <t:{int(remind_at.timestamp())}:R> です。")
    else:
        await interaction.followup.send("現在、リマインドは設定されていません。`/bump` をお願いします！")

@tasks.loop(minutes=1)
async def reminder_task():
    reminder = await db.get_reminder()
    if reminder:
        now = datetime.datetime.now(datetime.timezone.utc)
        if now >= reminder['remind_at']:
            try:
                channel = bot.get_channel(reminder['channel_id']) or await bot.fetch_channel(reminder['channel_id'])
                if channel:
                    await channel.send("⏰ そろそろBumpの時間だよ！`/bump` をお願いします！")
                await db.clear_reminder()
                print("リマインドメッセージを送信し、設定を削除しました。")
            except Exception as e:
                print(f"リマインダータスクでエラー: {e}")

# --- Renderのスリープを防ぐためのWebサーバー機能 ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!", 200

@app.route('/health')
def health_check():
    return "OK", 200

def run_flask():
    # daemon=Trueにすることで、メインスレッド終了時にFlaskも終了する
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True)
    flask_thread.start()

# --- BotとWebサーバーを同時に動かす ---
# ここがメインの処理
run_flask() # 先にFlask（おまじない）を起動
bot.run(TOKEN) # その後にBot（BUMPくん本体）を起動
