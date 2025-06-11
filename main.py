import discord
from discord import app_commands
import os
import threading
import logging
from dotenv import load_dotenv
from flask import Flask
import database as db

# --- 初期設定 ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- 環境変数と定数 ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))
URGENT_ROLE_ID = int(os.getenv("URGENT_ROLE_ID", 0)) # ★新しい環境変数を読み込む★

# --- Discord Botの準備 ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- スリープ対策Webサーバーの準備 ---
# (この部分は変更なし)
app = Flask(__name__)
@app.route('/')
def home(): return "Shugoshin Bot is watching over you."
def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- Botのイベント処理 ---
# (on_readyは変更なし)
@client.event
async def on_ready():
    await db.init_shugoshin_db()
    await tree.sync()
    logging.info(f"✅ 守護神ボットが起動しました: {client.user}")


# --- 管理コマンドのグループ ---
# (/reportmanageは変更なし)
report_manage_group = app_commands.Group(name="reportmanage", description="報告を管理します。")
@report_manage_group.command(name="status", description="報告のステータスを変更します。")
# (statusの中身も省略)
# ...
@report_manage_group.command(name="list", description="報告の一覧を表示します。")
# (listの中身も省略)
# ...
@report_manage_group.command(name="stats", description="報告の統計情報を表示します。")
# (statsの中身も省略)
# ...


# ★★★★★★★ Ver1.3 ここからがメインの改造部分 ★★★★★★★

@tree.command(name="report", description="サーバーのルール違反を匿名で管理者に報告します。")
@app_commands.describe(
    target_user="報告したい相手",
    violated_rule="違反したと思われるルール",
    urgency="報告の緊急度を選択してください。",
    details="（「その他」を選んだ場合は必須）具体的な状況を教えてください。",
    message_link="証拠となるメッセージのリンク（任意）"
)
@app_commands.choices(
    violated_rule=[
        app_commands.Choice(name="そのいち：ひとをきずつけない 💔", value="そのいち：ひとをきずつけない 💔"),
        # (他のルール選択肢は省略)
    ],
    urgency=[ # ★緊急度の選択肢を追加★
        app_commands.Choice(name="低：通常の違反報告", value="低"),
        app_commands.Choice(name="中：早めの対応が必要", value="中"),
        app_commands.Choice(name="高：即座の対応が必要", value="高"),
    ]
)
async def report(
    interaction: discord.Interaction,
    target_user: discord.User,
    violated_rule: app_commands.Choice[str],
    urgency: app_commands.Choice[str], # ★引数を追加★
    details: str = None,
    message_link: str = None
):
    if violated_rule.value == "その他" and not details:
        await interaction.response.send_message("「その他」を選んだ場合は、具体的な状況を `details` に入力してください。", ephemeral=True)
        return
        
    try:
        # 1. DBに通報を保存（urgencyも一緒に）
        report_id = await db.create_report(
            interaction.guild.id, target_user.id, violated_rule.value, details, message_link, urgency.value
        )

        report_channel = client.get_channel(REPORT_CHANNEL_ID)
        
        # 2. 緊急度に応じてメッセージの内容と色を変える
        embed_color = discord.Color.greyple() # デフォルトは低
        title_prefix = "📝"
        content = None

        if urgency.value == "中":
            embed_color = discord.Color.orange()
            title_prefix = "⚠️"
        elif urgency.value == "高":
            embed_color = discord.Color.red()
            title_prefix = "🚨"
            # 緊急度「高」の場合、ロールにメンション
            if URGENT_ROLE_ID != 0:
                role = interaction.guild.get_role(URGENT_ROLE_ID)
                if role:
                    content = f"{role.mention} 緊急の報告です！"
                else:
                    logging.warning(f"緊急メンション用のロール(ID: {URGENT_ROLE_ID})が見つかりません。")

        # 3. 埋め込みメッセージを作成
        embed = discord.Embed(
            title=f"{title_prefix} 新規の匿名報告 (ID: {report_id})",
            color=embed_color
        )
        embed.add_field(name="👤 報告対象者", value=f"{target_user.mention} ({target_user.id})", inline=False)
        embed.add_field(name="📜 違反したルール", value=violated_rule.value, inline=False)
        embed.add_field(name="🔥 緊急度", value=urgency.value, inline=False) # 緊急度フィールドを追加
        if details: embed.add_field(name="📝 詳細", value=details, inline=False)
        if message_link: embed.add_field(name="🔗 関連メッセージ", value=message_link, inline=False)
        embed.add_field(name="📊 ステータス", value="未対応", inline=False)
        embed.set_footer(text="この報告は匿名で送信されました。")

        # 4. 報告チャンネルにメッセージとメンションを投稿
        sent_message = await report_channel.send(content=content, embed=embed)
        await db.update_report_message_id(report_id, sent_message.id)

        await interaction.response.send_message("通報を受け付けました。ご協力ありがとうございます。", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"不明なエラーが発生しました: {e}", ephemeral=True)
        logging.error(f"通報処理中にエラー: {e}", exc_info=True)


# --- 起動処理 ---
def main():
    tree.add_command(report_manage_group)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    client.run(TOKEN)

if __name__ == "__main__":
    main()
