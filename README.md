# CraftSwitcher v2
Minecraft Java サーバー 管理システム |
[DNC6](https://github.com/Necnion8/dnCoreV6)プラグイン実装
<br>
本体コードは [dncore/extensions/craftswitcher](dncore%2Fextensions%2Fcraftswitcher) にあります

---
## 開発中
- [x] DNC6プラグイン化
- [x] サーバープロセスの操作ラッパー
- [ ] REST API / WebSocket
- [ ] 非同期ファイル操作マネージャ
- [ ] アーカイブファイルの操作
- [ ] サーバー内連携モジュール
- [ ] Discordからの操作コマンド
- [ ] サーバーJarの準備
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
- Linux (推奨)
- Windows (一部の機能は非対応)

※ macOSは未確認。おそらく動作？

## 対応予定サーバー
- Vanilla
- Spigot
- Paper
- BungeeCord
- Waterfall
- Velocity
- Forge
- NeoForge
- Fabric


## 導入と起動
```bash
# Install
python3 -m pip install -r requirements.txt

# Launch
python3 -m dncore
```
初回の起動時に以下のファイルが生成されます。
- `./config/config.yml` - dnCore設定
- `./plugins/CraftSwitcherPlugin/config.yml` - メイン設定

Discord機能を利用しない場合は[無効にする方法](https://github.com/Necnion8/dnCoreV6/wiki/No-Connect-Discord)を参照ください。 
