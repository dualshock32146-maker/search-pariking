# バイク駐輪場マップ 東京

東京都内のバイク（自動二輪）駐車場を、1日の上限料金つきで地図に表示する個人用Webアプリ。

公開URL: https://dualshock32146-maker.github.io/search-pariking/

## できること
- ピンに **1日の上限料金**（なければ1時間料金）を表示。色は 〜500円 / 〜1,000円 / 〜2,000円 / それ以上 / 不明
- 上限料金・時間貸/予約制・お気に入りで絞り込み
- 駅名・地名検索（国土地理院 住所検索API）、現在地から近い順の一覧
- 詳細シートから Googleマップでナビ、予約制は予約サイト、時間貸は s-park／公社ライブカメラで空き確認
- 「空いてた／満車だった」を端末に記録（自分用の混雑メモ）

## 空き状況について
都内バイク駐車場のリアルタイム満空はオープンデータで提供されていないため、地図には表示していない。
s-park は利用規約でデータの複製・二次利用を禁じているため、データは取り込まずリンクのみにしている。

## データの更新
```sh
# 1. JMPSA 一覧の取得（区市ごとの件数ファイルが必要: "区市名 件数" の行）
python3 scripts/scrape_jmpsa.py counts.txt out/jmpsa.json
# 2. OSM（Overpass API）
curl --data-urlencode data@scripts/osm_query.overpassql https://maps.mail.ru/osm/tools/overpass/api/interpreter -o out/osm.json
# 3. 統合
python3 scripts/build_data.py "out/jmpsa*.json" --osm out/osm.json -o data/parking.json
```

## データ出典
- 一般社団法人 日本二輪車普及安全協会「全国バイク駐車場案内」 https://www.jmpsa.or.jp/society/parking/area13/
- © OpenStreetMap contributors（ODbL）
- 地図タイル・地名検索：国土地理院（地理院タイル、住所検索API）
