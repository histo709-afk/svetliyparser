"""Bulk import routes from hardcoded city→destination mapping."""
from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.repositories.route_repo import RouteRepository

router = Router(name="bulk_import")

PARSER_CHANNELS = {
    "Агрыз": -1003314102219,
    "Азнакаево": -1002306192334,
    "Аксубаево": -1002722532541,
    "Альметьевск": -1002375481064,
    "Арск": -1002894687997,
    "Бавлы": -1002678080592,
    "Бугульма": -1002338611836,
    "Буинск": -1002294675759,
    "Елабуга": -1002470607229,
    "Заинск": -1003452123191,
    "Зеленодольск": -1002270183572,
    "Казань": -1002309479057,
    "Кукмор": -1003251645262,
    "Лениногорск": -1002255449935,
    "Мамадыш": -1002267076011,
    "Менделеевск": -1002278794882,
    "Мензелинск": -1002525537473,
    "Набережные Челны": -1002444719835,
    "Нижнекамск": -1002426955146,
    "Нурлат": -1002242130345,
    "Сарманово": -1003245765848,
    "Тетюши": -1003310384333,
    "Уруссу": -1002510849498,
    "Чистополь": -1002363465738,
}

CITY_SOURCES = {
    "Агрыз": ['agr_vesti', 'typikalagryz', 'mypervieagryz', 'agryz_online', 'agryz_official', 'lenarnurgayanov', 'bdd_agryz', 'mupagriz'],
    "Азнакаево": ['mayakonline', 'molodezhka_azn2020', 'mypervieaznakaevo', 'aznakaevo_novosti', 'Official_Aznakay', 'marsel_shaydullin_official'],
    "Аксубаево": ['selskayanovaksubaevo', 'Almaz_Mingulov', 'aksubayevoofficial', 'mypervieaksubayevo', 'netrezvievoditelAksubaevo'],
    "Альметьевск": ['almet_novosti', 'almetyevskcity', 'spotalmet', 'almetyevsk_1', 'uvt24', 'inde_almet', 'pressalmet', 'myperviealmetyevsk', 'almet_times', 'tatneft_telegram', 'mupsvetservis'],
    "Арск": ['beznen_arsk', 'arskklovee', 'arskmedia', 'odms_arskRT', 'myperviearsk', 'arskiirayon', 'arskobsudim', 'arsksosh1', 'mc_algarish', 'arskped', 'arskdvorec', 'arsksh2', 'khisamutdinovalmaz'],
    "Бавлы": ['BavlyinformNEWS', 'tnbavly', 'myperviebavly'],
    "Бугульма": ['bugulma_inform', 'rodnayabugulma', 'bugulgazeta', 'dps_bugulma', 'bogulma', 'myperviebugulma', 'damir_fattakhov', 'dvorec_molodezhi', 'bugulma_ws'],
    "Буинск": ['official_bua', 'buinsknews', 'myperviebuinsk', 'mboyli6', 'buinskijvettehnikum', 'buamedrese', 'RanisKamartdinov'],
    "Елабуга": ['ElabugaNK', 'onlineelabuga', 'elabuga_opergruppa', 'TvoyaElabyga', 'mr_Rustem_Nuriev', 'elabuga_novosti', 'alabugapolytech', 'mypervieyalabuga', 'elabuga_official', 'ELABUGA0', 'AlabugaOEZ'],
    "Заинск": ['zainsknews', 'myperviezainsk', 'KarimovRG', 'dkenergetikzay', 'zainskiimr'],
    "Зеленодольск": ['zpravda', 'zelenodolsk_news', 'myperviezelenodolsk', 'zel_official', 'zelenodolskpolice', 'zelencrb', 'zel_med', 'gibdd116zelenodolsk', 'mihailafanasev'],
    "Казань": ['Kazan_bezopasno', 'zhest_dtp16', 'eduvtatarstan', 'kzn_official', 'tatmediaofficial', 'kazanfirst', 'minmol_rt16', 'eveningkzn', 'kazan_smi', 'kazan_chat0', 'region116_kazan', 'businessgazeta', 'kazancity', 'vestitatarstan', 'mincult_rt', 'gazetabo', 'tatarstan_republic', 'kazanvkp', 'gokzn', 'minsport_rt', 'kazan', 'propskzn', 'prokrt', 'realnoevremya', 'kazankay', 'enter_media', 'mash_iptash', 'kazany', 'apparatustatar', 'rustamminnikhanov', 'transportkazan', 'ivf_rt', 'mvdtatarstana', 'o16rf', 'su_skr16', 'gibddtatarstan', 'Tatarstan24TV', 'kazan_da', 'rtRBC', 'galimovatatarstan', 'toptatarstan'],
    "Кукмор": ['kukmor_tatarstan', 'kukmor_tv', 'myperviekukmor', 'kukmormaks', 'kukmorschool3'],
    "Лениногорск": ['leninogorsk_city_rt', 'leninogorsk_novosti', 'len_vesti', 'Girfanovmn', 'mypervieleninogorsk', 'mc_leninogorsk', 'leninogorsk_yarmarka', 'lensk_official', 'OMVDLeninogorsk', 'leninogorskgibdd', 'lencrb2022', 'school2leninogorsk'],
    "Мамадыш": ['novosti_mamadysha', 'myperviemamadysh', 'news_mamadysh', 'mamadysh_novosti', 'vyatka16resort', 'mamadysh_online', 'kama_mamadysh'],
    "Менделеевск": ['mndnews', 'myperviemendeleevsk', 'mendeleevsk_rt', 'iskandarovrobert'],
    "Мензелинск": ['menzelinskfm', 'molodezhmz', 'officiall_menz', 'myperviemenzelinsk', 'smi_menzela', 'menzelinsk_online', 'aidar041964'],
    "Набережные Челны": ['chpchelny', 'chelny_sity', 'chelny_online716', 'chelny_onIine', 'chelny_chs', 'chelnylife', 'mcnurnch', 'chelny_news1', 'nabchelnyofficial', 'chelny_itch', 'chelnykuda', 'chelnytv', 'rimmachelny', 'nail_magdeev', 'molod_chelny', 'bsmp_nabchelny', 'zdravchelny', 'mypervienabchelny'],
    "Нижнекамск": ['nkvknew', 'novosti_tat', 'nka_112', 'podslunk', 'ntr24ru', 'nizhnekamsk_life', 'moynizhnekamsk', 'mypervienizhnekamsk', 'narod_nk', 'nizhnekamsknow', 'radmirbelyaev'],
    "Нурлат": ['nurlatinform', 'dtp_nurlat', 'lenar1565', 'mypervienurlat', 'nurlat_news', 'chsnurlat', 'damirishkineev'],
    "Сарманово": ['sarmanovo_sarman', 'sarman_rt', 'myperviesarmanovo', 'husnullinfaritmunavirovich'],
    "Тетюши": ['tetyushy', 'tetushi_official', 'ramis_safiullov', 'mypervietetushi', 'tetyshigibdd'],
    "Уруссу": ['utazinkaurussu', 'kras_urussu', 'VodaUrussu', 'myperviejutaza', 'yazshafigullin', 'urussucrb', 'czn_yutazy'],
    "Чистополь": ['naBebelya', 'chistopol_news', 'myperviechistopol', 'chistopol_official', 'DmitriyIvanov1972', 'Chistopol_molod', 'chistopolie', 'news_chistopol', 'trezvo_chistopol'],
}


@router.message(Command("bulk_import"))
async def bulk_import(message: Message) -> None:
    from app.telethon_client.client import telethon_client
    from app.services.channel_service import resolve_channel

    await message.answer("⏳ Начинаю массовый импорт маршрутов (публичные каналы, без flood limit)...")

    added = 0
    skipped = 0
    errors = []

    for city, dest_id in PARSER_CHANNELS.items():
        sources = CITY_SOURCES.get(city, [])
        if not sources:
            continue

        # Ensure destination exists in DB
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            dest = await repo.get_destination_by_telegram_id(dest_id)
            if dest is None:
                dest = await repo.add_destination(
                    telegram_id=dest_id,
                    username=None,
                    title=f"Парсер {city}",
                )
                await session.commit()

        for username in sources:
            try:
                info = await resolve_channel(telethon_client, username)
                if info is None:
                    errors.append(f"{username}: не найден")
                    continue

                async with async_session_factory() as session:
                    repo = ChannelRepository(session)
                    route_repo = RouteRepository(session)

                    src = await repo.get_source_by_telegram_id(info.telegram_id)
                    if src is None:
                        src = await repo.add_source(
                            telegram_id=info.telegram_id,
                            username=info.username,
                            title=info.title,
                        )

                    dest = await repo.get_destination_by_telegram_id(dest_id)
                    existing = await route_repo.get_route(src.id, dest.id)
                    if existing:
                        skipped += 1
                    else:
                        await route_repo.add_route(src.id, dest.id)
                        added += 1
                    await session.commit()

                await asyncio.sleep(0.3)

            except Exception as e:
                errors.append(f"{username}: {str(e)[:50]}")

    text = f"✅ <b>Импорт завершён!</b>\n\n"
    text += f"• Добавлено маршрутов: <b>{added}</b>\n"
    text += f"• Уже существовало: <b>{skipped}</b>\n"
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n"
        text += "\n".join(errors[:15])

    await message.answer(text, parse_mode="HTML")
