"""
Canonical IDX Sharia-compliant trading universe (DES list).

This list used to be copy-pasted verbatim into three separate scripts, which is
exactly why a fix applied in one file could silently miss the others. It now
lives here once. Import it everywhere:

    from kala.universe import ALL_SHARIA_STOCKS, WATCHLIST
"""

ALL_SHARIA_STOCKS = [
    'AADI.JK', 'AALI.JK', 'ABMM.JK', 'ACES.JK', 'ADCP.JK', 'ADES.JK',
    'ADMG.JK', 'ADMR.JK', 'ADRO.JK', 'AEGS.JK', 'AGAR.JK', 'AGII.JK',
    'AISA.JK', 'AKPI.JK', 'AKRA.JK', 'AKSI.JK', 'ALDO.JK', 'ALKA.JK',
    'AMAN.JK', 'AMFG.JK', 'AMIN.JK', 'AMMS.JK', 'ANTM.JK', 'APII.JK',
    'APLI.JK', 'APLN.JK', 'ARCI.JK', 'AREA.JK', 'ARII.JK', 'ARNA.JK',
    'ASGR.JK', 'ASHA.JK', 'ASLC.JK', 'ASLI.JK', 'ASPI.JK', 'ASPR.JK',
    'ASRI.JK', 'ASSA.JK', 'ATAP.JK', 'ATIC.JK', 'ATLA.JK', 'AUTO.JK',
    'AVIA.JK', 'AWAN.JK', 'AXIO.JK', 'AYAM.JK', 'AYLS.JK', 'BABY.JK',
    'BAIK.JK', 'BALI.JK', 'BANK.JK', 'BAPI.JK', 'BATR.JK', 'BAUT.JK',
    'BAYU.JK', 'BBRM.JK', 'BBSS.JK', 'BCIP.JK', 'BDKR.JK', 'BELI.JK',
    'BELL.JK', 'BESS.JK', 'BEST.JK', 'BIKE.JK', 'BINO.JK', 'BIPP.JK',
    'BIRD.JK', 'BISI.JK', 'BKDP.JK', 'BKSL.JK', 'BLES.JK', 'BLOG.JK',
    'BLTA.JK', 'BLTZ.JK', 'BLUE.JK', 'BMBL.JK', 'BMHS.JK', 'BMSR.JK',
    'BMTR.JK', 'BOAT.JK', 'BOBA.JK', 'BOGA.JK', 'BOLT.JK', 'BRAM.JK',
    'BRIS.JK', 'BRMS.JK', 'BRNA.JK', 'BRRC.JK', 'BSBK.JK', 'BSDE.JK',
    'BSML.JK', 'BSSR.JK', 'BTPS.JK', 'BUAH.JK', 'BUDI.JK', 'BULL.JK',
    'BUMI.JK', 'BWPT.JK', 'BYAN.JK', 'CAKK.JK', 'CAMP.JK', 'CANI.JK',
    'CARE.JK', 'CASH.JK', 'CASS.JK', 'CCSI.JK', 'CEKA.JK', 'CGAS.JK',
    'CHEK.JK', 'CHEM.JK', 'CHIP.JK', 'CINT.JK', 'CITA.JK', 'CITY.JK',
    'CLEO.JK', 'CLPI.JK', 'CMNP.JK', 'CMPP.JK', 'CMRY.JK', 'CNMA.JK',
    'COAL.JK', 'CPIN.JK', 'CPRO.JK', 'CRSN.JK', 'CSAP.JK', 'CSIS.JK',
    'CSMI.JK', 'CSRA.JK', 'CTBN.JK', 'CTRA.JK', 'CYBR.JK', 'DADA.JK',
    'DATA.JK', 'DAYA.JK', 'DCII.JK', 'DEFI.JK', 'DEPO.JK', 'DEWA.JK',
    'DEWI.JK', 'DGIK.JK', 'DGNS.JK', 'DGWG.JK', 'DILD.JK', 'DIVA.JK',
    'DKFT.JK', 'DMAS.JK', 'DMMX.JK', 'DMND.JK', 'DOOH.JK', 'DOSS.JK',
    'DRMA.JK', 'DSFI.JK', 'DSNG.JK', 'DSSA.JK', 'DUTI.JK', 'DVLA.JK',
    'DWGL.JK', 'DYAN.JK', 'EAST.JK', 'ECII.JK', 'EKAD.JK', 'ELIT.JK',
    'ELPI.JK', 'ELSA.JK', 'ELTY.JK', 'EMDE.JK', 'ENAK.JK', 'ENRG.JK',
    'EPAC.JK', 'EPMT.JK', 'ERAA.JK', 'ERAL.JK', 'ERTX.JK', 'ESIP.JK',
    'ESSA.JK', 'ESTA.JK', 'EURO.JK', 'EXCL.JK', 'FAST.JK', 'FASW.JK',
    'FILM.JK', 'FIMP.JK', 'FIRE.JK', 'FISH.JK', 'FLMC.JK', 'FMII.JK',
    'FOLK.JK', 'FOOD.JK', 'FORE.JK', 'FPNI.JK', 'FWCT.JK', 'GDST.JK',
    'GDYR.JK', 'GEMA.JK', 'GEMS.JK', 'GGRP.JK', 'GHON.JK', 'GIAA.JK',
    'GJTL.JK', 'GLVA.JK', 'GMTD.JK', 'GOLD.JK', 'GOLF.JK', 'GOOD.JK',
    'GPRA.JK', 'GPSO.JK', 'GRIA.JK', 'GRPH.JK', 'GRPM.JK', 'GTRA.JK',
    'GULA.JK', 'GUNA.JK', 'GWSA.JK', 'GZCO.JK', 'HADE.JK', 'HAIS.JK',
    'HAJJ.JK', 'HALO.JK', 'HATM.JK', 'HBAT.JK', 'HDIT.JK', 'HEAL.JK',
    'HELI.JK', 'HERO.JK', 'HEXA.JK', 'HOKI.JK', 'HOMI.JK', 'HOPE.JK',
    'HRTA.JK', 'HRUM.JK', 'HYGN.JK', 'IATA.JK', 'IBST.JK', 'ICBP.JK',
    'ICON.JK', 'IDEA.JK', 'IDPR.JK', 'IFII.JK', 'IFSH.JK', 'IGAR.JK',
    'IIKP.JK', 'IKAI.JK', 'IKAN.JK', 'IKBI.JK', 'IKPM.JK', 'IMPC.JK',
    'INCI.JK', 'INDF.JK', 'INDR.JK', 'INDS.JK', 'INDY.JK', 'INET.JK',
    'INKP.JK', 'INPP.JK', 'INTD.JK', 'INTP.JK', 'IOTF.JK', 'IPAC.JK',
    'IPCM.JK', 'IPOL.JK', 'IPTV.JK', 'IRRA.JK', 'IRSX.JK', 'ISAP.JK',
    'ISAT.JK', 'ISSP.JK', 'ITMA.JK', 'ITMG.JK', 'JARR.JK', 'JAST.JK',
    'JATI.JK', 'JAWA.JK', 'JAYA.JK', 'JECC.JK', 'JGLE.JK', 'JIHD.JK',
    'JKON.JK', 'JMAS.JK', 'JPFA.JK', 'JRPT.JK', 'JSMR.JK', 'JTPE.JK',
    'KAQI.JK', 'KARW.JK', 'KBAG.JK', 'KBLI.JK', 'KBLM.JK', 'KDSI.JK',
    'KEEN.JK', 'KEJU.JK', 'KETR.JK', 'KIAS.JK', 'KICI.JK', 'KIJA.JK',
    'KING.JK', 'KINO.JK', 'KIOS.JK', 'KJEN.JK', 'KKES.JK', 'KKGI.JK',
    'KLAS.JK', 'KLBF.JK', 'KLIN.JK', 'KMDS.JK', 'KOBX.JK', 'KOCI.JK',
    'KOIN.JK', 'KOKA.JK', 'KONI.JK', 'KOPI.JK', 'KOTA.JK', 'KPIG.JK',
    'KREN.JK', 'KUAS.JK', 'LABS.JK', 'LAJU.JK', 'LAND.JK', 'LFLO.JK',
    'LION.JK', 'LIVE.JK', 'LMAX.JK', 'LMPI.JK', 'LMSH.JK', 'LOPI.JK',
    'LPCK.JK', 'LPIN.JK', 'LPLI.JK', 'LPPF.JK', 'LRNA.JK', 'LSIP.JK',
    'LTLS.JK', 'LUCK.JK', 'MAHA.JK', 'MAIN.JK', 'MANG.JK', 'MAPA.JK',
    'MAPB.JK', 'MAPI.JK', 'MARK.JK', 'MAXI.JK', 'MBAP.JK', 'MBMA.JK',
    'MBTO.JK', 'MCAS.JK', 'MCOL.JK', 'MDIA.JK', 'MDIY.JK', 'MDKA.JK',
    'MDKI.JK', 'MDLA.JK', 'MEDC.JK', 'MEDS.JK', 'MEJA.JK', 'MERI.JK',
    'MERK.JK', 'META.JK', 'MFMI.JK', 'MGLV.JK', 'MHKI.JK', 'MICE.JK',
    'MIKA.JK', 'MINE.JK', 'MIRA.JK', 'MITI.JK', 'MKAP.JK', 'MKNT.JK',
    'MKPI.JK', 'MKTR.JK', 'MLIA.JK', 'MLPL.JK', 'MLPT.JK', 'MMIX.JK',
    'MMLP.JK', 'MNCN.JK', 'MORA.JK', 'MPIX.JK', 'MPMX.JK', 'MPOW.JK',
    'MPPA.JK', 'MRAT.JK', 'MSIE.JK', 'MSIN.JK', 'MSJA.JK', 'MSKY.JK',
    'MSTI.JK', 'MTDL.JK', 'MTEL.JK', 'MTLA.JK', 'MTMH.JK', 'MTPS.JK',
    'MTSM.JK', 'MUTU.JK', 'MYOH.JK', 'MYOR.JK', 'NAIK.JK', 'NANO.JK',
    'NASI.JK', 'NAYZ.JK', 'NELY.JK', 'NEST.JK', 'NFCX.JK', 'NICE.JK',
    'NICL.JK', 'NIKL.JK', 'NRCA.JK', 'NSSS.JK', 'NTBK.JK', 'NZIA.JK',
    'OBAT.JK', 'OBMD.JK', 'OKAS.JK', 'OLIV.JK', 'OMED.JK', 'PACK.JK',
    'PADA.JK', 'PALM.JK', 'PAMG.JK', 'PANR.JK', 'PART.JK', 'PBID.JK',
    'PCAR.JK', 'PDES.JK', 'PDPP.JK', 'PEHA.JK', 'PEVE.JK', 'PGAS.JK',
    'PGJO.JK', 'PGLI.JK', 'PGUN.JK', 'PICO.JK', 'PJAA.JK', 'PJHB.JK',
    'PKPK.JK', 'PLAN.JK', 'PLIN.JK', 'PMJS.JK', 'PMUI.JK', 'PNBS.JK',
    'PNGO.JK', 'POLI.JK', 'POLU.JK', 'PORT.JK', 'POWR.JK', 'PPGL.JK',
    'PPRE.JK', 'PPRI.JK', 'PRAY.JK', 'PRDA.JK', 'PRIM.JK', 'PSAB.JK',
    'PSAT.JK', 'PSDN.JK', 'PSGO.JK', 'PSKT.JK', 'PSSI.JK', 'PTBA.JK',
    'PTIS.JK', 'PTMP.JK', 'PTMR.JK', 'PTPP.JK', 'PTPS.JK', 'PTPW.JK',
    'PTSN.JK', 'PTSP.JK', 'PURA.JK', 'PURI.JK', 'PZZA.JK', 'RAAM.JK',
    'RAJA.JK', 'RALS.JK', 'RANC.JK', 'RATU.JK', 'RBMS.JK', 'RCCC.JK',
    'REAL.JK', 'RELF.JK', 'RGAS.JK', 'RISE.JK', 'RMKE.JK', 'RMKO.JK',
    'ROCK.JK', 'RODA.JK', 'ROTI.JK', 'RSCH.JK', 'RSGK.JK', 'RUIS.JK',
    'RUNS.JK', 'SAFE.JK', 'SAGE.JK', 'SAME.JK', 'SAMF.JK', 'SAPX.JK',
    'SATU.JK', 'SBMA.JK', 'SCCO.JK', 'SCNP.JK', 'SCPI.JK', 'SDPC.JK',
    'SEMA.JK', 'SGER.JK', 'SGRO.JK', 'SHID.JK', 'SICO.JK', 'SIDO.JK',
    'SILO.JK', 'SIMP.JK', 'SIPD.JK', 'SKBM.JK', 'SKLT.JK', 'SKRN.JK',
    'SLIS.JK', 'SMAR.JK', 'SMBR.JK', 'SMCB.JK', 'SMDM.JK', 'SMDR.JK',
    'SMGA.JK', 'SMGR.JK', 'SMIL.JK', 'SMKL.JK', 'SMKM.JK', 'SMLE.JK',
    'SMMT.JK', 'SMRA.JK', 'SMSM.JK', 'SNLK.JK', 'SOCI.JK', 'SOFA.JK',
    'SOHO.JK', 'SOLA.JK', 'SOSS.JK', 'SOTS.JK', 'SPMA.JK', 'SPRE.JK',
    'SPTO.JK', 'SRTG.JK', 'SSIA.JK', 'SSTM.JK', 'STAA.JK', 'STTP.JK',
    'SULI.JK', 'SUNI.JK', 'SUPR.JK', 'SURI.JK', 'SWID.JK', 'TALF.JK',
    'TAMA.JK', 'TAPG.JK', 'TAXI.JK', 'TBMS.JK', 'TCID.JK', 'TCPI.JK',
    'TEBE.JK', 'TFAS.JK', 'TFCO.JK', 'TGKA.JK', 'TGUK.JK', 'TINS.JK',
    'TIRA.JK', 'TIRT.JK', 'TKIM.JK', 'TLDN.JK', 'TLKM.JK', 'TMAS.JK',
    'TMPO.JK', 'TNCA.JK', 'TOBA.JK', 'TOOL.JK', 'TOSK.JK', 'TOTL.JK',
    'TOTO.JK', 'TPIA.JK', 'TPMA.JK', 'TRIS.JK', 'TRJA.JK', 'TRON.JK',
    'TRST.JK', 'TRUK.JK', 'TSPC.JK', 'TYRE.JK', 'UANG.JK', 'UCID.JK',
    'UDNG.JK', 'UFOE.JK', 'ULTJ.JK', 'UNIC.JK', 'UNIQ.JK', 'UNTR.JK',
    'UNVR.JK', 'URBN.JK', 'UVCR.JK', 'VAST.JK', 'VERN.JK', 'VICI.JK',
    'VISI.JK', 'VKTR.JK', 'VOKS.JK', 'WAPO.JK', 'WBSA.JK', 'WEGE.JK',
    'WEHA.JK', 'WGSH.JK', 'WIDI.JK', 'WIFI.JK', 'WINR.JK', 'WINS.JK',
    'WIRG.JK', 'WOOD.JK', 'WOWS.JK', 'WTON.JK', 'YELO.JK', 'YPAS.JK',
    'YUPI.JK', 'ZONE.JK', 'ZYRX.JK'
]

WATCHLIST = ALL_SHARIA_STOCKS

# When YOU last refreshed ALL_SHARIA_STOCKS from the official ISSI list
# (ISO date string, e.g. "2026-07-10"). IDX revises the list roughly twice a
# year (around May and November); trading a stale list means potentially
# holding names that are no longer sharia-compliant — the one constraint this
# whole project is built around.
UNIVERSE_UPDATED: str | None = "2026-07-22"


def staleness_warning(today=None, max_age_days: int = 185):
    """One-line warning string if the ISSI list is stale (or its refresh date
    unknown), else None. Called by daily_run so the reminder lands in the
    daily Telegram message instead of relying on memory."""
    from datetime import date as _date

    if today is None:
        from .clock import today_wib
        today = today_wib()
    if UNIVERSE_UPDATED is None:
        return ("⚠️ ISSI list: refresh date unknown — set UNIVERSE_UPDATED in "
                "kala/universe.py after verifying the list against the "
                "latest official ISSI revision (~May & ~Nov).")
    age = (today - _date.fromisoformat(UNIVERSE_UPDATED)).days
    if age > max_age_days:
        return (f"⚠️ ISSI list is {age} days old (last refreshed {UNIVERSE_UPDATED}); "
                f"IDX revises it ~May & ~Nov — refresh ALL_SHARIA_STOCKS.")
    return None


# ---------------------------------------------------------------------------
# US sharia-compliant large-cap starter universe
# ---------------------------------------------------------------------------
#
# PROVENANCE — READ BEFORE TRUSTING THIS LIST.
#
# This is NOT a scrape of any live index's current constituents. Every
# attempt to fetch one this session (stockanalysis.com, sp-funds.com,
# gurufocus.com, an SEC N-PORT filing) was blocked (HTTP 403) by the
# sandbox's outbound web-fetch path. Rather than reconstruct an "exact"
# 200+ name list from partial search-result snippets — which risks silently
# inventing tickers that were never really constituents — this is a
# hand-curated, conservative STARTER set: large, liquid, financially strong
# US companies from sectors that essentially every major Islamic-finance
# screen (AAOIFI-style debt/interest-income ratios, Dow Jones Islamic
# Market, S&P Shariah) treats as uncontroversially compliant, built from
# general knowledge of that screening methodology, not from any specific
# fund's disclosed holdings.
#
# Deliberately EXCLUDED (i.e. don't assume these should be added):
#   * Financials: banks, insurers, asset managers, financial exchanges/data
#     (conventional interest-based business, or excluded outright by name
#     e.g. SPUS's methodology specifically drops "Financial Exchanges &
#     Data" and "Data Processing & Outsourced Services" -- which is why
#     payment networks like Visa/Mastercard/PayPal are NOT in this list,
#     despite being fee-revenue businesses -- too methodology-dependent to
#     include without verification).
#   * Aerospace & Defense (excluded by several shariah methodologies,
#     including SPUS's, regardless of the debt/interest screen).
#   * Alcohol, tobacco, gambling/casinos, pork products, adult entertainment
#     (no large-caps of this kind appear here, so nothing to exclude by
#     name, but flagging the screen for completeness).
#   * Health INSURERS specifically (conventional insurance, not healthcare
#     generally -- device/pharma/biotech names are kept).
#   * Anything carrying meaningfully high debt/interest-income ratios that
#     can't be verified without live financials (e.g. most telecoms,
#     utilities, and heavily-leveraged names) -- left out rather than
#     guessed at.
#
# BEFORE TRADING OR EVEN BACKTESTING SERIOUSLY ON THIS LIST: cross-check
# every ticker you actually care about against a live shariah screener
# (e.g. the fund's own current holdings page, Zoya, Musaffa, IdealRatings)
# -- compliance status changes as companies' debt/interest-income ratios
# move, exactly the same "list goes stale" risk ALL_SHARIA_STOCKS has
# above, just without a tracked UNIVERSE_UPDATED date yet because this
# list has no verified "as of" source date to begin with.
#
# Bare tickers (no exchange suffix) -- this is how yfinance expects US names.

US_SHARIA_STOCKS = [
    # Technology / semiconductors
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ORCL', 'ADBE', 'CRM',
    'AMD', 'QCOM', 'TXN', 'CSCO', 'IBM', 'NOW', 'INTU', 'AMAT', 'LRCX',
    'KLAC', 'MU', 'PANW', 'SNPS', 'CDNS', 'ANET', 'ROP',
    # Healthcare (device / pharma / biotech -- NOT insurers)
    'JNJ', 'ABBV', 'LLY', 'MRK', 'TMO', 'ABT', 'DHR', 'ISRG', 'VRTX',
    'REGN', 'GILD',
    # Consumer (ex-alcohol / ex-tobacco)
    'AMZN', 'COST', 'WMT', 'HD', 'NKE', 'MCD', 'PG', 'KO', 'PEP', 'CL', 'EL',
    # Industrials / materials / energy (ex-aerospace & defense)
    'XOM', 'CVX', 'LIN', 'CAT', 'DE', 'HON', 'EMR', 'ECL',
    # Communications / media
    'NFLX', 'CMCSA',
]
