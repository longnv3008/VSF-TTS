# Bao Cao Tong Quan He Thong

## 1. Muc tieu he thong

He thong nay duoc xay dung de tu dong thu thap va xu ly audio tieng Viet tu YouTube.

He thong co 2 cach lay du lieu:

- Cach 1: nguoi dung tu nhap URL YouTube
- Cach 2: he thong tu tim URL moi khi da xu ly xong batch cu

Sau khi co URL, he thong se:

- tai audio
- chuan hoa audio
- tao file dich/noi dung xu ly tiep theo
- ghi metadata de phuc vu thong ke va su dung sau nay

Noi ngan gon, day la mot pipeline tu dong hoa viec lay audio va to chuc du lieu theo batch.

## 2. He thong dang chay nhu the nao

Luong hoat dong don gian nhu sau:

1. Nguoi dung gui vao mot lo URL YouTube
2. He thong chia thanh tung job nho de de xu ly
3. Moi URL duoc crawl va xu ly theo cac buoc co dinh
4. Khi batch ket thuc, he thong kiem tra xem con viec nao dang chay khong
5. Neu he thong dang ranh, mot agent se tu tim them URL moi va tao batch tiep theo

Y nghia:

- He thong khong chi phu thuoc vao URL do nguoi dung nhap
- Sau nay co the van hanh ban tu dong, lien tuc tim noi dung moi

## 3. Nhung thanh phan chinh

Co the hieu he thong gom 4 phan don gian:

- API
  - noi nhan request tu frontend hoac nguoi dung
- Database
  - luu batch, job, URL, trang thai thanh cong hay that bai
- Worker
  - chay nen de xu ly tung job
- Discovery agent
  - tu tim URL moi khi he thong dang ranh

## 4. Pipeline xu ly hien tai

Moi URL di qua 5 buoc chinh:

1. Kiem tra va chuan hoa URL
2. Crawl audio tu YouTube
3. Chuan hoa audio
4. Tao phan noi dung/dich
5. Ghi metadata tong hop

Ket qua cuoi cung duoc luu thanh file de de kiem tra va dung lai.

## 5. Cach he thong dung cookie

Cookie duoc dung de tang kha nang crawl khi YouTube yeu cau dang nhap hoac bat dau kho hon voi guest session.

He thong hien co 3 tang:

1. Cookie chinh
2. Cookie du phong
3. Guest session

Y nghia:

- Neu cookie chinh dung duoc thi uu tien dung no
- Neu cookie chinh loi thi thu bang cookie du phong
- Neu ca 2 cookie deu loi thi bo cookie va chay guest

Uu diem:

- He thong khong dung ngay chi vi 1 cookie hong
- Van co duong lui de tiep tuc crawl URL public

Luu y:

- Cookie YouTube de bi het han hoac bi rotate
- Log warning ve cookie khong co nghia la URL se that bai ngay
- Nhieu video public van co the crawl duoc bang guest

## 6. Cach he thong dung proxy

He thong dang dung chien luoc don gian va an toan:

- Binh thuong dung IP chinh cua may/server
- Chi khi bi limit thi moi chuyen sang proxy backup

Khong dung kieu xoay proxy lien tuc.

Y nghia:

- Giu hanh vi giong nguoi dung that hon
- Giam nguy co session dang dang nhap bi danh dau la bat thuong
- De theo doi xem IP nao dang tot, IP nao dang bi limit

## 7. Khi bi rate limit thi he thong xu ly ra sao

Neu IP hien tai bi YouTube limit:

1. He thong danh dau IP do tam thoi khong dung
2. Cho IP do nghi trong mot khoang thoi gian
3. Neu co proxy backup thi chuyen sang proxy backup
4. Thu lai chinh URL dang do

Neu khong co proxy backup:

- Job hien tai co the phai cho den khi IP chinh duoc thu lai

Moc cau hinh hien tai:

- Thoi gian cooldown khi bi block: `900 giay = 15 phut`

Y nghia van hanh:

- He thong khong crash
- Nhung batch dang xu ly co the bi cham neu chi co 1 IP

## 8. Retry thong minh la gi

He thong khong retry moi loi theo cung 1 cach.

Hien tai chia thanh 3 nhom:

- Loi mang nhe
  - vi du timeout, reset ket noi
  - he thong retry 1 lan tren cung route

- Loi bi limit/bot/block
  - he thong cooldown IP hien tai
  - neu co proxy thi chuyen proxy
  - roi retry lai dung URL do

- Loi auth/noi dung cung
  - vi du video private, members-only
  - he thong khong retry vo ich

Uu diem:

- Tiet kiem tai nguyen
- Giam spam request
- Dung retry dung cho tung loai loi

## 9. Discovery agent dang lam gi

Discovery agent la phan tu tim URL moi mot cach tu dong.

No chi bat dau lam viec khi:

- mot batch vua xu ly xong
- va database khong con job nao dang `queued`, `running`, hoac `blocked`

Sau do no:

- cho mot khoang ngan
- doc topic trong `topic.txt`
- search YouTube theo tung nhom topic
- loc bot ket qua khong phu hop
- tao batch moi

Y nghia:

- He thong co kha nang tu tiep noi batch
- Giam phu thuoc vao viec nguoi dung nhap URL bang tay

## 10. Topic file duoc dung nhu the nao

`topic.txt` la file chua cac chu de tim kiem.

He thong hien dang co:

- `70 topic`

Nhung he thong khong quet tat ca 70 topic moi lan.

Thay vao do, he thong chia theo cua so:

- moi vong chi quet `20 topic`

Sau moi vong, he thong nho lai da dung toi dau trong file topic bang mot file con tro:

- `data/discovery/topic_cursor.json`

Y nghia:

- Vong 1 quet 20 topic dau
- Vong 2 quet 20 topic tiep theo
- Vong 3 quet tiep nua
- Het file thi quay lai dau

Uu diem:

- Khong qua tai do phai search toan bo topic moi lan
- Moi topic deu co co hoi duoc quet
- Phu hop hon neu sau nay topic tang len rat nhieu

## 11. He thong dang do luong va biet duoc gi

Hien tai he thong da co cac thong tin co the bao cao duoc:

### Cau hinh van hanh hien tai

- So URL toi da trong 1 job: `50`
- So URL muc tieu moi vong discovery: `20`
- So topic quet moi vong: `20`
- Thoi gian cho truoc khi discovery bat dau: `5-10 giay`
- Thoi gian cooldown khi IP bi block: `15 phut`

### Log/Thong bao da co

He thong da log va gui Telegram cho:

- batch bat dau / ket thuc / dung lai
- cookie warning / cookie error / cookie switch
- proxy switch / proxy limit / proxy error
- discovery bat dau tim URL
- discovery tao batch moi
- canh bao ve quyen ghi file va duong dan

### Dieu nay giup do duoc gi

Tu cac log hien tai, co the theo doi:

- batch nao thanh cong, batch nao that bai
- URL nao bi skip
- cookie co con dung duoc hay khong
- proxy co dang bi limit hay khong
- moi vong discovery tim duoc bao nhieu URL
- he thong dang dung topic file hay fallback env

### Dieu chua co day du

Hien tai chua co dashboard tong hop chinh thuc de xem nhanh:

- ti le thanh cong/thất bại
- thoi gian trung binh moi batch
- so lan phai chuyen proxy
- so lan cookie chinh hong va phai roi sang cookie backup/guest

Neu can bao cao chuyen nghiep hon, day la phan nen bo sung tiep.

## 12. Danh gia thoi gian va anh huong van hanh

### Discovery

- He thong co chu dong cho `5-10 giay` truoc khi tim URL moi
- Muc dich la tranh vua xong batch da search ngay lap tuc
- Dieu nay giup he thong tu nhien hon, de giam tai tuc thoi

### Proxy cooldown

- Khi bi rate limit, IP bi cho nghi `15 phut`
- Neu co proxy backup, he thong tiep tuc duoc
- Neu khong co proxy backup, batch co the phai cho

### Tac dong thuc te

- Neu chi co 1 IP: de bi cham khi YouTube limit
- Neu co 2-3 proxy backup: kha nang tiep tuc xu ly tot hon ro ret
- Neu cookie bi hong som: guest session van cuu duoc nhieu URL public, nhung do on dinh se giam

## 13. Cac bien phap dang duoc su dung va danh gia

### 1. Dung cookie

Muc dich:

- Giu kha nang crawl cao hon guest

Uu diem:

- Lay duoc nhieu noi dung hon
- Giam bot mot so bot challenge

Nhuoc diem:

- Cookie YouTube rat de het han
- Phai export lai dinh ky

De xuat:

- Dung 1 account phu rieng cho crawl
- Co 1 cookie chinh va 1 cookie backup
- Theo doi log Telegram de thay som luc cookie hong

### 2. Dung proxy backup

Muc dich:

- Giam nguy co batch dung lai khi IP chinh bi limit

Uu diem:

- He thong co duong lui khi IP chinh gap van de
- Giup batch tiep tuc duoc thay vi cho hoan toan

Nhuoc diem:

- Neu proxy kem chat luong hoac sai cau hinh, loi van xay ra
- Doi IP nhieu co the lam cookie bi danh dau bat thuong

De xuat:

- Dung IP chinh truoc
- Chi failover sang proxy khi thuc su bi limit
- Uu tien proxy on dinh, khong nen xoay loạn lien tuc

### 3. Dung discovery agent

Muc dich:

- Tu dong noi tiep batch moi khi he thong ranh

Uu diem:

- Giam thao tac tay
- Giup pipeline co the van hanh lien tuc

Nhuoc diem:

- Ket qua discovery van phu thuoc search YouTube
- Chua phai tim kiem "thong minh" cap cao

De xuat:

- Duy tri topic file ro rang, co chu de tot
- Sau nay nen luu lich su topic nao cho ra URL chat luong cao

## 14. Nhung diem tot hien tai

- Da co luong xu ly batch ro rang
- Da co co che retry thong minh
- Da co fallback cookie va guest
- Da co proxy failover khi can
- Da co tu dong tim URL moi
- Da co log va Telegram de theo doi van hanh
- Da co giam race condition cho discovery

## 15. Nhung diem can luu y voi mentor

1. He thong da co the chay ban tu dong, nhung chua phai muc production lon
2. Cookie va proxy la hai bien phap quan trong nhat de giam rate limit
3. Neu khong co proxy backup, khi IP chinh bi limit thi batch co the bi tre
4. Discovery da tu dong hon truoc, nhung van la heuristic-based
5. He thong da co log kha day du, nhung chua co dashboard thong ke tong hop
6. Van de quyen file giua local va Docker la diem can theo doi ky

## 16. De xuat tiep theo

### Uu tien ngan han

- Bo sung dashboard hoac endpoint thong ke tong hop
- Luu them lich su discovery de tranh lap lai qua nhieu URL cu
- Theo doi so lan cookie hong va so lan switch proxy de danh gia hieu qua

### Uu tien trung han

- Dua state proxy/cooldown vao DB thay vi de trong memory
- Danh gia topic nao cho ra ket qua tot nhat
- Uu tien topic/chatnel co chat luong cao hon

### Uu tien dai han

- Tach discovery thanh service rieng neu muon scale lon
- Dung worker queue chuyen nghiep hon neu tai tang manh
- Tao dashboard theo doi batch, URL, proxy, cookie, discovery

## 17. Ket luan ngan gon

He thong hien tai da vuot muc "nguoi dung nhap URL roi crawl thu cong".

No da co:

- xu ly batch
- retry thong minh
- cookie fallback
- proxy failover
- discovery agent tu tim URL moi
- log Telegram de theo doi van hanh

Danh gia tong the:

- Phu hop de demo, nghien cuu va van hanh quy mo nho-den-vua
- Co nen tang tot de tiep tuc mo rong
- Buoc tiep theo nen tap trung vao thong ke, do luong va do ben van hanh khi crawl quy mo lon
