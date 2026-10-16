# ポータルサイト（SUUMO等）の読み方

WebFetchではSUUMOの物件ページを取得できないことが多い（2026年9月に404を確認）。Claude in Chrome（ユーザーのChrome）で読む。

## SUUMO：1往復で本文と間取り図を取る
1. 初回のみ `chrome-browser` スキルを読み、ツールを1回のToolSearchでまとめて読み込む：
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__tabs_close_mcp`
2. URLの物件コード（`bc_` の後ろの12桁、例 123456789012）から間取り図のURLを組み立てる：
   `https://img01.suumo.com/front/gazo/fr/bukken/<コードの下3桁>/<コード>/<コード>_co.jpg`
   例：123456789012 → `.../bukken/012/123456789012/123456789012_co.jpg`（2026年9月に2物件で動作確認済み）
3. まず `navigate`（tabIdなし）で物件ページを開き、返ってきたtabIdを使って `browser_batch` を1回だけ実行する：
   - `get_page_text`（物件ページ）
   - `navigate`（間取り図のURL）
   - `computer` の `screenshot`
4. 間取り図の文字が小さくて読めないときだけ、`zoom` で図面部分を拡大する（画像は画面中央に原寸表示される）。
5. 作ったタブは最後に閉じる。

### 間取り図のURLが開けないとき（404・別の画像）
物件ページに戻り、`javascript_tool` で次を実行して画像URLを取り出し、そのURLを開く：
```js
[...document.querySelectorAll('img')].filter(i => /間取/.test(i.alt||'')).map(i => i.dataset.src || i.src)[0]
```

## 本文から拾う項目
賃料、管理費、敷金・礼金、間取り、間取り詳細、専有面積、向き、築年月、階建、所在地、駅徒歩、契約期間（定期借家の満了）、仲介手数料、保証会社（初回・月額）、ほか初期費用、ほか諸費用、備考（短期解約違約金、退去時清掃費など）、入居時期、総戸数。

## 間取り図から読む項目
方位記号と各窓の向き、各室の広さ、収納、冷蔵庫置き場、柱の出っ張り、共用廊下側の部屋。寸法の記載がなければ「採寸が必要」とする。

## Chromeが使えないとき
- 内蔵ブラウザが使えればそちらで同じ手順を行う
- どちらも使えなければ、「物件概要」と「間取り図」のスクリーンショット2枚をユーザーに依頼する

## 注意
- SUUMOの所在地は丁目までのことが多い。建物名で places_search して番地と緯度経度を特定する
- 掲載情報は仲介会社の入力で、誤りがあり得る。契約条件は重要事項説明書で最終確認する
