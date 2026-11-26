# バイク駐輪場マップ 東京

東京都内の時間貸しバイク（自動二輪）駐車場を、1時間料金・1日最大料金つきで地図に表示する個人用Webアプリ。

公開URL: https://dualshock32146-maker.github.io/search-pariking/

## できること
- ピンに **1時間停めた料金** と **1日の最大料金**（24時間停めた場合の目安）を表示。色は1日最大で 〜500円 / 〜1,000円 / 〜2,000円 / それ以上・上限なし / 不明
- **平日・土曜・日曜祝日** を区別。今日の区分（祝日・振替休日・国民の休日も判定）の料金を自動で表示し、チップで切り替え可能。詳細シートでは区分ごとの料金表と定休日を表示
- 1時間料金・1日最大料金・お気に入りで絞り込み
- 駅名・地名検索（国土地理院 住所検索API）、現在地から近い順の一覧
- 詳細シートから Googleマップでナビ、s-park／公社ライブカメラで空き確認
- 「空いてた／満車だった」を端末に記録（自分用の混雑メモ）
- 予約制（akippa・特P など）は掲載しない

## 料金の読み取りについて
- 掲載元（JMPSA）の料金は自由記述の文章なので、`scripts/price.py` で「1時間停めた料金」「24時間停めた料金」に換算している。最初の無料時間、時間帯別料金、最大料金（繰り返しあり/1回限り）、車種別料金（高い方＝自動二輪を採用）を考慮
- 自動で正しく読めない文面（曜日で料金が違うもの、時間帯ごとの最大料金など）は `scripts/price_overrides.py` に手入力
- 曜日の違いは、料金文の「月〜金／土日祝」などの記載と、定休日欄（「日曜・祝日」など）から判定。記載がないものは毎日同じ料金とみなしている
- 掲載元の最終更新日が3年以上前のものは、詳細シートで注意を表示

## 空き状況について
都内バイク駐車場のリアルタイム満空はオープンデータで提供されていないため、地図には表示していない。
s-park は利用規約でデータの複製・二次利用を禁じているため、データは取り込まずリンクのみにしている。

## データの更新
```sh
# 1. JMPSA 一覧の取得（区市ごとの件数ファイルが必要: "区市名 件数" の行）
python3 scripts/scrape_jmpsa.py counts.txt out/jmpsa.json
# 2. OSM（Overpass API）
curl --data-urlencode data@scripts/osm_query.overpassql https://maps.mail.ru/osm/tools/overpass/api/interpreter -o out/osm.json
# 3. 詳細ページ（利用可能時間・最終更新日）。予約制以外のみ、0.4秒間隔
python3 scripts/fetch_jmpsa_detail.py data/parking.json out/detail.json
# 4. 統合
python3 scripts/build_data.py "out/jmpsa*.json" --osm out/osm.json --detail out/detail.json -o data/parking.json
# 料金の読み取りだけやり直すとき（再スクレイプなし）
python3 scripts/build_data.py --prev data/parking.json --detail out/detail.json -o data/parking.json
```

## データ出典
- 一般社団法人 日本二輪車普及安全協会「全国バイク駐車場案内」 https://www.jmpsa.or.jp/society/parking/area13/
- © OpenStreetMap contributors（ODbL）
- 地図タイル：OpenStreetMap Japan（OSM Bright 日本語版、標準）、OpenStreetMap、国土地理院（地理院タイル）。右上のボタンで切替
- 地名検索：国土地理院 住所検索API
