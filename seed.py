"""
Test ma'lumotlarini bazaga yozadi.

    python seed.py            # bazada seed ma'lumot bo'lmasa yozadi
    python seed.py --reset    # AVVAL BARCHA ma'lumotni o'chiradi (tasdiq so'raydi)
"""
import argparse
import shutil
import uuid
from io import BytesIO
from urllib.request import Request, urlopen
from datetime import date, datetime, timedelta, timezone
from app.services.tour_option_service import DEFAULT_POLICY
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, text as sql

from app.database import Base, SessionLocal, engine
import app.models  # noqa: F401
from app.models.agency_model import (
    AgencyDocument, AgencyMember, AgencyMemberRole, AgencyProfile, AgencyStatus,
    DocumentType,
)
from app.models.booking_model import Booking, BookingStatus
from app.models.chat_model import Conversation, Message
from app.models.notification_model import Notification, NotificationType
from app.models.tour_model import (
    Departure, Review, SavedTour, Tour, TourCategory, TourImage,
    TourItineraryDay, TourStatus,
)
from app.models.user_model import User, UserRole
from app.security import hash_password
from app.services.storage_service import MEDIA_ROOT, PRIVATE_ROOT

PASSWORD = "Seed12345"          # hamma test akkauntlar uchun
ADMIN_EMAIL = "admin@sayohatapp.uz"
NOW = datetime.now(timezone.utc)
TODAY = date.today()


# ---------------------------------------------------------------- rasmlar
PALETTES = {
    "sea": ((0, 119, 182), (144, 224, 239)),
    "mountain": ((45, 106, 79), (183, 228, 199)),
    "city": ((84, 84, 120), (240, 160, 120)),
    "culture": ((157, 78, 40), (246, 214, 150)),
}
_IMG_CACHE: dict[str, Image.Image | None] = {}


def download_image(url: str) -> Image.Image | None:
    """URL dan rasmni yuklaydi. Xato bo'lsa None (seed to'xtamaydi)."""
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    img = None
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 SayohatSeed"})
        with urlopen(req, timeout=20) as r:
            data = r.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("rasm 8 MB dan katta")
        img = Image.open(BytesIO(data))
        img.load()
        img = img.convert("RGB")
        img.thumbnail((1600, 1600))
    except Exception as e:
        print(f"  ! Rasm yuklanmadi ({url[:70]}...): {e}")
        img = None
    _IMG_CACHE[url] = img
    return img


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # eski Pillow
        return ImageFont.load_default()


def make_image(category: str, label: str, variant: int, size=(1200, 800)) -> Image.Image:
    top, bottom = PALETTES[category]
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    k = 0.7 + 0.15 * variant

    for y in range(size[1]):
        t = min(1.0, y / (size[1] - 1) * k)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size[0], y)], fill=color)
    draw.text((60, size[1] - 140), label, fill=(255, 255, 255), font=_font(56))
    return img


def save_placeholder(root, folder: str, img: Image.Image) -> str:
    target = root / folder
    target.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(target / name, "JPEG", quality=85)
    return f"{folder}/{name}"


# ---------------------------------------------------------------- ma'lumot
# (ism, familiya, email, telefon)
TRAVELERS = [
    ("Shohijahon", "Zaynidinov", "traveler1@sayohatapp.uz", "+998901110001"),
    ("Dilnoza", "Karimova", "traveler2@sayohatapp.uz", "+998901110002"),
    ("Jasur", "Rahmonov", "traveler3@sayohatapp.uz", "+998901110003"),
]

# (egasi ismi, familiyasi, email, telefon, agentlik nomi, litsenziya, STIR,
#  viloyat, shahar, manzil, status)
AGENCIES = [
    ("Aziz", "Tursunov", "agency1@sayohatapp.uz", "+998902220001", "Silk Road Travel",
     "TL-2021-0451", "301245678", "Toshkent", "Toshkent", "Amir Temur ko'chasi 15", "approved"),
    ("Malika", "Yusupova", "agency2@sayohatapp.uz", "+998902220002", "Sunrise Tour",
     "TL-2020-0187", "302556781", "Toshkent", "Toshkent", "Navoiy ko'chasi 42", "approved"),
    ("Bobur", "Aliyev", "agency3@sayohatapp.uz", "+998902220003", "Registon Journeys",
     "TL-2019-0093", "303667892", "Samarqand", "Samarqand", "Registon ko'chasi 7", "approved"),
    ("Sardor", "Qodirov", "agency4@sayohatapp.uz", "+998902220004", "Yangi Yo'l Travel",
     "TL-2026-0702", "304778903", "Toshkent", "Toshkent", "Mustaqillik ko'chasi 3", "pending"),
]

# agentlik indeksi, sarlavha, shahar, davlat, kategoriya, kun, narx, eski narx,
# mehmonxona, ovqat, transport, guruh, til, hot, trending, jo'nashlar (kun offseti, joy)
TOURS = [
    (0, "Antalya: 5 yulduzli dam olish", "Antalya", "Turkiya", "sea", 7, 6_900_000, 7_800_000,
     "Rixos Premium 5*", "Hammasi kiritilgan", "Aviareys", "20 kishi", "O'zbek, Rus", True, True,
     [(-30, 20), (14, 20), (35, 20)]),
    (0, "Dubay: shahar va cho'l safari", "Dubay", "BAA", "city", 5, 8_400_000, None,
     "Rove Downtown 4*", "Nonushta", "Aviareys", "15 kishi", "O'zbek, Ingliz", True, False,
     [(10, 15), (30, 15)]),
    (1, "Sharm-el-Sheyx: qizil dengiz", "Sharm-el-Sheyx", "Misr", "sea", 8, 7_200_000, 8_100_000,
     "Albatros Palace 5*", "Hammasi kiritilgan", "Aviareys", "25 kishi", "O'zbek, Rus", True, True,
     [(12, 25), (40, 25)]),
    (1, "Chimyon va Charvoq tog'lari", "Chimyon", "O'zbekiston", "mountain", 2, 650_000, None,
     "Tog' uyi", "Tushlik", "Mikroavtobus", "12 kishi", "O'zbek, Rus", False, True,
     [(5, 12), (12, 12), (19, 12)]),
    (2, "Samarqand: Buyuk Ipak yo'li", "Samarqand", "O'zbekiston", "culture", 3, 1_450_000, 1_700_000,
     "Registan Plaza 4*", "Nonushta", "Tezyurar poyezd", "15 kishi", "O'zbek, Rus, Ingliz", False, True,
     [(7, 15), (21, 15), (45, 15)]),
    (2, "Buxoro va Xiva: qadimiy shaharlar", "Buxoro", "O'zbekiston", "culture", 5, 3_200_000, None,
     "Minzifa Boutique 4*", "Nonushta, kechki ovqat", "Avtobus", "14 kishi", "O'zbek, Ingliz", False, False,
     [(15, 14), (38, 14)]),
    (2, "Tbilisi va Batumi", "Tbilisi", "Gruziya", "city", 6, 9_800_000, 11_000_000,
     "Rooms Hotel 4*", "Nonushta", "Aviareys", "16 kishi", "O'zbek, Rus", False, False,
     [(20, 16), (50, 16)]),
    (1, "Alp tog'lari: Shveytsariya", "Interlaken", "Shveytsariya", "mountain", 9, 21_500_000, None,
     "Hotel Metropole 4*", "Nonushta", "Aviareys", "10 kishi", "Ingliz, Rus", False, False,
     [(60, 10)]),
]
DRAFT_TOUR = (0, "Maldiv orollari (qoralama)", "Male", "Maldiv", "sea", 7, 18_000_000, None,
              "Resort 5*", "Hammasi kiritilgan", "Aviareys", "8 kishi", "Ingliz", False, False, [])

# Tur sarlavhasi -> rasm havolalari (birinchisi muqova rasmi)

TOUR_IMAGES: dict[str, list[str]] = {
    "Antalya: 5 yulduzli dam olish": [
        "https://images.unsplash.com/photo-1542051841857-5f90071e7989?auto=format&fit=crop&w=1200&q=80"
    ],
    "Dubay: shahar va cho'l safari": [
        "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80"
    ],
    "Sharm-el-Sheyx: qizil dengiz": [
        "https://images.unsplash.com/photo-1544551763-46a013bb70d5?auto=format&fit=crop&w=1200&q=80"
    ],
    "Chimyon va Charvoq tog'lari": [
        "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1200&q=80"
    ],
    "Samarqand: Buyuk Ipak yo'li": [
        "https://images.unsplash.com/photo-1584551246679-0daf3d275d0f?auto=format&fit=crop&w=1200&q=80"
    ],
    "Buxoro va Xiva: qadimiy shaharlar": [
        "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&w=1200&q=80"
    ],
    "Tbilisi va Batumi": [
        "https://images.unsplash.com/photo-1565008447742-97f6f38c985c?auto=format&fit=crop&w=1200&q=80"
    ],
    "Alp tog'lari: Shveytsariya": [
        "https://images.unsplash.com/photo-1530122037265-a5f1f91d3b99?auto=format&fit=crop&w=1200&q=80"
    ],
    "Maldiv orollari (qoralama)": [
        "https://images.unsplash.com/photo-1514282401047-d79a71a590e8?auto=format&fit=crop&w=1200&q=80"
    ],
}

INCLUDED = ["Turar joy", "Transfer", "Gid xizmati", "Sug'urta"]
EXCLUDED = ["Viza to'lovi", "Shaxsiy xarajatlar", "Qo'shimcha ekskursiyalar"]

# (tur indeksi, foydalanuvchi indeksi, baho, matn)
REVIEWS = [
    (0, 0, 5, "Hammasi a'lo darajada tashkil etilgan, mehmonxona juda yoqdi."),
    (0, 1, 4, "Yaxshi sayohat bo'ldi, faqat parvoz vaqti noqulay edi."),
    (0, 2, 5, "Oilam bilan bordik, bolalar juda xursand bo'ldi."),
    (1, 1, 5, "Cho'l safari unutilmas bo'ldi, gid juda bilimdon."),
    (2, 0, 4, "Dengiz va servis yaxshi, ovqatlar xilma-xil."),
    (3, 2, 4, "Qisqa, lekin ajoyib dam olish. Havo toza."),
    (4, 0, 5, "Samarqand tarixini yaxshi tushuntirishdi."),
    (4, 1, 5, "Tashkilot a'lo, vaqtida hamma joyga yetib bordik."),
    (5, 2, 4, "Xiva juda ta'sirli, Buxoroda ko'proq vaqt bo'lsa yaxshi edi."),
]


# ---------------------------------------------------------------- yordamchilar
def reset_all() -> None:
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(sql(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    for root, sub in ((MEDIA_ROOT, "tours"), (MEDIA_ROOT, "avatars"),
                      (MEDIA_ROOT, "logos"), (PRIVATE_ROOT, "agency-docs")):
        shutil.rmtree(root / sub, ignore_errors=True)
    print("Baza va fayllar tozalandi.")


def itinerary_for(days: int, city: str) -> list[TourItineraryDay]:
    items = []
    for d in range(1, days + 1):
        if d == 1:
            title, body = "Kelish va joylashish", f"{city}ga kelish, mehmonxonaga joylashish, shahar bilan tanishuv."
        elif d == days:
            title, body = "Qaytish", "Nonushta, sovg'alar uchun erkin vaqt va uyga qaytish."
        else:
            title, body = f"{d}-kun: ekskursiya", f"{city} bo'ylab gid hamrohligida ko'rilishi kerak joylar va erkin vaqt."
        items.append(TourItineraryDay(day=d, title=title, text=body))
    return items


def make_booking(db, code, user, tour, dep, guests, status, consume=True) -> Booking:
    paid = status in (BookingStatus.confirmed, BookingStatus.completed)
    b = Booking(
        code=code, user_id=user.id, tour_id=tour.id, departure_id=dep.id,
        guests=guests, unit_price=tour.price, addons_total=0, total=tour.price * guests,
        status=status, policy_snapshot=DEFAULT_POLICY,
        confirmed_at=NOW if paid else None,
    )
    db.add(b)
    if consume:
        dep.seats_left -= guests
        if paid:
            tour.bookings_count += 1
    return b


# ---------------------------------------------------------------- asosiy
def seed() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).where(User.email == TRAVELERS[0][2])):
            print("Seed ma'lumotlar allaqachon bor. Qayta yozish uchun: python seed.py --reset")
            return

        pwd = hash_password(PASSWORD)  # bcrypt sekin, bir marta hisoblaymiz

        # --- admin
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            admin = User(first_name="Admin", last_name="Sayohat", email=ADMIN_EMAIL,
                         phone="+998900000000", password_hash=pwd,
                         role=UserRole.admin, is_email_verified=True)
            db.add(admin)

        # --- oddiy foydalanuvchilar
        travelers = []
        for first, last, email, phone in TRAVELERS:
            u = User(first_name=first, last_name=last, email=email, phone=phone,
                     password_hash=pwd, role=UserRole.traveler, is_email_verified=True)
            db.add(u)
            travelers.append(u)
        db.flush()

        # --- agentliklar, egalari (owner), managerlar va hujjatlar
        agencies: list[AgencyProfile] = []
        managers: dict[uuid.UUID, User] = {}   # agentlik id -> manager
        for first, last, email, phone, name, lic, tax, region, city, addr, st in AGENCIES:
            owner = User(first_name=first, last_name=last, email=email, phone=phone,
                         password_hash=pwd, role=UserRole.agency, is_email_verified=True)
            profile = AgencyProfile(
                name=name, license_number=lic, tax_id=tax, region=region, city=city,
                address=addr, contact_phone=phone, website=f"https://{name.split()[0].lower()}.uz",
                description=f"{name}: {city} shahridagi turistik agentlik.",
                status=AgencyStatus(st),
                reviewed_by=admin.id if st == "approved" else None,
                reviewed_at=NOW if st == "approved" else None,
            )
            owner.owned_agency = profile
            owner.membership = AgencyMember(agency=profile, role=AgencyMemberRole.owner)
            db.add(owner)
            db.flush()

            logo = Image.new("RGB", (400, 400), (230, 90, 50))
            ImageDraw.Draw(logo).text((140, 170), name[:2].upper(), fill="white", font=_font(90))
            profile.logo_path = save_placeholder(MEDIA_ROOT, f"logos/{profile.id}", logo)

            doc_types = ([DocumentType.license, DocumentType.tax_certificate, DocumentType.registration]
                         if st == "approved" else [DocumentType.license])
            for dt in doc_types:
                doc_img = Image.new("RGB", (900, 1200), "white")
                ImageDraw.Draw(doc_img).text((60, 60), f"TEST HUJJAT: {dt.value}\n{name}",
                                             fill="black", font=_font(40))
                path = save_placeholder(PRIVATE_ROOT, f"agency-docs/{profile.id}", doc_img)
                db.add(AgencyDocument(agency_id=profile.id, type=dt, file_path=path,
                                      is_checked=(st == "approved")))

            # tasdiqlangan agentlikka manager (agency admin) qo'shamiz
            if st == "approved":
                n = len(agencies) + 1
                mgr = User(first_name="Admin", last_name=name.split()[0],
                           email=f"manager{n}@sayohatapp.uz", phone=f"+99890333000{n}",
                           password_hash=pwd, role=UserRole.agency, is_email_verified=True)
                mgr.membership = AgencyMember(agency=profile, role=AgencyMemberRole.manager)
                db.add(mgr)
                managers[profile.id] = mgr

            agencies.append(profile)
        db.flush()

        # --- turlar
        tours: list[Tour] = []
        deps: dict[uuid.UUID, list[Departure]] = {}
        for row in TOURS + [DRAFT_TOUR]:
            (ai, title, city, country, cat, days, price, old, hotel, meals, transport,
             group, lang, hot, trending, departures) = row
            draft = row is DRAFT_TOUR
            tour = Tour(
                agency_id=agencies[ai].id, title=title, city=city, country=country,
                category=TourCategory(cat), days=days, price=price, old_price=old,
                description=f"{title}. {days} kunlik sayohat: qulay joylashuv, tajribali gid va yaxshi tashkil etilgan dastur.",
                hotel=hotel, meals=meals, transport=transport, group_size=group, language=lang,
                included=INCLUDED, excluded=EXCLUDED, hot=hot, trending=trending,
                status=TourStatus.draft if draft else TourStatus.published,
            )
            tour.itinerary = itinerary_for(days, city)
            tour.departures = [
                Departure(start_date=TODAY + timedelta(days=off), seats_total=seats, seats_left=seats)
                for off, seats in departures
            ]
            db.add(tour)
            db.flush()

            # Muhim: turlar ro'yxatiga va deps lug'atiga qo'shiladi
            tours.append(tour)
            deps[tour.id] = tour.departures

            images = [im for im in (download_image(u) for u in TOUR_IMAGES.get(title, [])[:10]) if im]
            if not images:  # havola yo'q yoki hammasi ishlamadi: gradient
                images = [make_image(cat, title, pos) for pos in range(3)]
            for pos, im in enumerate(images):
                path = save_placeholder(MEDIA_ROOT, f"tours/{tour.id}", im)
                db.add(TourImage(tour_id=tour.id, path=path, position=pos))

        # --- bronlar
        past = deps[tours[0].id][0]       # 30 kun oldingi jo'nash
        make_booking(db, "SY-DEMO01", travelers[0], tours[0], past, 2, BookingStatus.completed)
        make_booking(db, "SY-DEMO02", travelers[1], tours[1], deps[tours[1].id][0], 2, BookingStatus.confirmed)
        make_booking(db, "SY-DEMO03", travelers[0], tours[2], deps[tours[2].id][0], 3, BookingStatus.confirmed)
        make_booking(db, "SY-DEMO04", travelers[2], tours[4], deps[tours[4].id][0], 1, BookingStatus.confirmed)

        # --- sharhlar
        for ti, ui, rating, body in REVIEWS:
            db.add(Review(tour_id=tours[ti].id, user_id=travelers[ui].id, rating=rating, text=body))

        # --- saqlangan turlar
        for ui, ti in [(0, 1), (0, 4), (0, 6), (1, 0), (2, 2)]:
            db.add(SavedTour(user_id=travelers[ui].id, tour_id=tours[ti].id))

        # --- chat: traveler1 <-> agency1 (tur 0); agentlik tomonidan manager yozadi
        manager1 = managers[agencies[0].id]
        conv = Conversation(user_id=travelers[0].id, agency_id=agencies[0].id, tour_id=tours[0].id)
        db.add(conv)
        db.flush()
        chat = [
            (travelers[0], "Assalomu alaykum, Antalya turiga viza kerakmi?", 90, True),
            (manager1, "Va alaykum assalom! O'zbekiston fuqarolariga viza kerak emas.", 80, True),
            (travelers[0], "Rahmat. Narxga transfer kiradimi?", 30, True),
            (manager1, "Ha, aeroportdan mehmonxonagacha transfer narxga kiritilgan.", 5, False),
        ]
        for sender, body, minutes_ago, read in chat:
            ts = NOW - timedelta(minutes=minutes_ago)
            db.add(Message(conversation_id=conv.id, sender_id=sender.id, text=body,
                           created_at=ts, read_at=ts if read else None))
            conv.last_message_text, conv.last_message_at = body, ts

        # --- bildirishnomalar
        def note(user, type_, title, body, kind, target_id, ago_h, read=False):
            ts = NOW - timedelta(hours=ago_h)
            db.add(Notification(user_id=user.id, type=type_, title=title, text=body,
                                target_kind=kind, target_id=target_id, created_at=ts,
                                read_at=ts if read else None))

        t0 = travelers[0]
        note(t0, NotificationType.message, agencies[0].name,
             "Ha, aeroportdan mehmonxonagacha transfer narxga kiritilgan.", "chat", conv.id, 0.1)
        note(t0, NotificationType.price_drop, "Narx tushdi",
             f"{tours[1].title}: narx kamaydi", "tour", tours[1].id, 3)
        note(t0, NotificationType.booking, "Bron qabul qilindi",
             f"«{tours[2].title}» (SY-DEMO03) agentlik javobini kutmoqda", "bookings", None, 30)
        note(t0, NotificationType.promo, "Kuzgi chegirmalar",
             "Tanlangan turlarga 15% gacha chegirma", None, None, 120, read=True)

        # agentlik xodimlari (egasi va manager) ikkalasiga ham
        for staff in (agencies[0].user, manager1):
            note(staff, NotificationType.booking, "Yangi bron",
                 f"{travelers[0].full_name} «{tours[2].title}» turiga bron qildi",
                 "bookings", None, 28)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("\nSeed tayyor. Hamma akkauntlar paroli:", PASSWORD)
    print(f"  Admin:         {ADMIN_EMAIL}")
    print(f"  Foydalanuvchi: {TRAVELERS[0][2]}, {TRAVELERS[1][2]}, {TRAVELERS[2][2]}")
    print("  Agentlik egasi (owner, tasdiqlangan): agency1@, agency2@, agency3@sayohatapp.uz")
    print("  Agentlik admini (manager):            manager1@, manager2@, manager3@sayohatapp.uz")
    print("  Agentlik (kutilayotgan):              agency4@sayohatapp.uz")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="avval barcha ma'lumotni o'chirish")
    args = parser.parse_args()

    if args.reset:
        db_name = engine.url.database
        answer = input(f"'{db_name}' bazasidagi BARCHA ma'lumot o'chadi. Davom etasizmi? (ha/yo'q): ")
        if answer.strip().lower() != "ha":
            raise SystemExit("Bekor qilindi.")
        reset_all()
    seed()