# CraftSwitcher v2
Minecraft Java サーバー 管理システム |
[DNC6](https://github.com/Necnion8/dnCoreV6)プラグイン実装
<br>
本体コードは [dncore/extensions/craftswitcher](dncore%2Fextensions%2Fcraftswitcher) にあります

---
## 開発中
- [x] DNC6プラグイン化
- [x] サーバープロセスの操作ラッパー
- [x] REST API
- [x] WebSocket
- [x] 非同期ファイル操作マネージャ
- [x] アーカイブファイルの操作
- [x] サーバーJarのインストール
- [ ] サーバー内連携モジュール
- [ ] Discordからの操作コマンド (仮コマンド済み)
- [ ] リリース！

---
## 主な機能
- Webパネル
- Discord ボット (オプション)
- サーバー内 連携API
- ファイル操作
- パフォーマンスモニター
- DNC6プラグインによる機能の拡張


## 環境
- Python 3.10
- Linux (推奨)
- Windows

※ macOSは未確認。おそらく動作？

## 対応予定サーバー
- [Vanilla](https://www.minecraft.net/ja-jp/download/server)
- [Spigot](https://www.spigotmc.org/wiki/buildtools/)
- [Paper](https://papermc.io/software/paper)
- [Purpur](https://purpurmc.org/)
- [Folia](https://papermc.io/software/folia)
- [Forge](https://files.minecraftforge.net/)
- [Mohist](https://mohistmc.com/software/mohist)
- [NeoForge](https://neoforged.net/)
- [Youer](https://mohistmc.com/software/youer)*?*
- [Fabric](https://fabricmc.net/)
- [Banner](https://mohistmc.com/software/banner)
- [BungeeCord](https://www.spigotmc.org/wiki/bungeecord/)
- [Waterfall](https://papermc.io/software/waterfall)
- [Velocity](https://papermc.io/software/velocity)


## 導入と起動
```bash
# Install
python3 -m pip install -r requirements.txt

# Launch
python3 -m dncore
```
初回の起動時に以下のファイルが生成されます。
- `./config/config.yml` - dnCore設定
- `./plugins/CraftSwitcher/config.yml` - メイン設定


### Discord
Discord機能を利用しない場合は[無効にする方法](https://github.com/Necnion8/dnCoreV6/wiki/No-Connect-Discord)を参照ください。

### REST API
REST API は初期設定で [`http://0.0.0.0:8080/docs`](http://localhost:8080/docs) に公開されています。


## WebSocket
WebSocket クライアントを `http://0.0.0.0:8080/ws` に接続することで、サーバーイベント等を JSON フォーマットで受信できます。

### WS 受信
> [craftswitcher.py](dncore%2Fextensions%2Fcraftswitcher%2Fcraftswitcher.py)<br>
> `# events ws broadcast` このコマンド行の以下に実装があります


### WS 送信
> サーバープロセスへのテキストの書き込み
> ```json
> {
>   "type": "server_process_write",
>   "server": "lobby",
>   "data": "say Hello\r\n"
> }
> ```
