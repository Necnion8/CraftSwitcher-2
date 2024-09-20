# CraftSwitcher v2
Minecraft Java サーバー 管理システム |
[DNC6](https://github.com/Necnion8/dnCoreV6)プラグイン実装
<br>
本体コードは [dncore/extensions/craftswitcher](dncore%2Fextensions%2Fcraftswitcher) にあります

---
## 開発中
- [x] DNC6プラグイン化
- [x] サーバープロセスの操作ラッパー
- [x] REST API + WebSocketイベント
- [x] ファイル管理
- [x] アーカイブファイルの対応
- [x] サーバーのインストール
- [ ] バックアップ
- [ ] スケジューラー
- [ ] サーバー内連携モジュール
- [ ] Discordコマンド
- [ ] リリース！

---
## 主な機能
- Web UI
- Discord ボット (オプション)
- サーバー内 連携API
- ファイル操作
- パフォーマンスモニター
- バックアップとスケジュール機能


## 環境
- Python 3.10
- Linux (推奨)
- Windows

※ macOSは未確認。おそらく動作？

## 対応サーバー
| サーバー          | 基本操作 | 連携 | ダウンロード | ビルド |                             URL                              |
|:--------------|:----:|:--:|:------:|:---:|:------------------------------------------------------------:|
| Vanilla       |  ?   | ✕  |   〇    |  -  | [Minecraft](https://www.minecraft.net/ja-jp/download/server) |     |     |
| Spigot        |  ?   | ✕  |   〇    |  〇  |    [SpigotMC](https://www.spigotmc.org/wiki/buildtools/)     |     |     |
| Paper         |  ?   | ✕  |   〇    |  -  |         [PaperMC](https://papermc.io/software/paper)         |     |     |
| Purpur        |  ?   | ✕  |   〇    |  -  |              [PurpurMC](https://purpurmc.org/)               |     |     |
| Folia         |  ?   | ✕  |   〇    |  -  |         [PaperMC](https://papermc.io/software/folia)         |     |     |
| # ***mod***   |
| Forge         |  ?   | ✕  |   〇    |  〇  |     [Minecraft Forge](https://files.minecraftforge.net/)     |     |     |
| Mohist        |  ?   | ✕  |   〇    |  -  |       [MohistMC](https://mohistmc.com/software/mohist)       |     |     |
| NeoForge      |  ?   | ✕  |   〇    |  〇  |             [NeoForged](https://neoforged.net/)              |     |     |
| Youer         |  ?   | ✕  |   ?    |  ?  |       [MohistMC](https://mohistmc.com/software/youer)        |     |     |
| Fabric        |  ?   | ✕  |   〇    |  -  |              [FabricMC](https://fabricmc.net/)               |     |     |
| Banner        |  ?   | ✕  |   〇    |  -  |       [MohistMC](https://mohistmc.com/software/banner)       |     |     |
| # ***proxy*** |
| BungeeCord    |  ?   | ✕  |   〇    |  -  |    [SpigotMC](https://www.spigotmc.org/wiki/bungeecord/)     |     |     |
| Waterfall     |  ?   | ✕  |   〇    |  -  |       [PaperMC](https://papermc.io/software/waterfall)       |     |     |
| Velocity      |  ?   | ✕  |   〇    |  -  |       [PaperMC](https://papermc.io/software/velocity)        |     |     |

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
