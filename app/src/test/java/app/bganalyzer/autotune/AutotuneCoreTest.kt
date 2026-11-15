package app.bganalyzer.autotune

import org.bson.Document
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.ZoneId

/** The two AndroidAPS autotune core test cases (AutotuneCoreTest.kt, 3.4.2.1), run against the Kotlin port. */
class AutotuneCoreTest {
    private fun read(path: String) = Document.parse(javaClass.getResource("/autotune/$path")!!.readText())
    private fun num(v: Any?) = when (v) { is Number -> v.toDouble(); is String -> v.toDouble(); else -> error("not a number: $v") }

    private fun profile(d: Document) = AtProfile(
        basal = (d["basalprofile"] as List<*>).map { num((it as Document)["rate"]) },
        isf = num(((d["isfProfile"] as Document)["sensitivities"] as List<*>).map { it as Document }[0]["sensitivity"]),
        ic = num(d["carb_ratio"]), dia = num(d["dia"]), peak = (d["insulinPeakTime"] as Number).toInt(),
    )

    private fun limits(d: Document) = AutotuneLimits(num(d["autosens_max"]), num(d["autosens_min"]), num(d["min_5m_carbimpact"]))

    private fun bg(d: Document) = BgDatum(
        date = (d["date"] as Number).toLong(), glucose = num(d["glucose"]), avgDelta = num(d["avgDelta"] ?: 0.0),
        bgi = num(d["BGI"] ?: 0.0), deviation = num(d["deviation"] ?: 0.0),
        mealAbsorption = d["mealAbsorption"] as? String ?: "", mealCarbs = (d["mealCarbs"] as? Number)?.toInt() ?: 0,
    )

    private fun prepped(d: Document) = PreppedGlucose(
        crData = (d["CRData"] as List<*>).map {
            val c = it as Document
            CrDatum(num(c["CRInitialBG"]), num(c["CRInitialIOB"]), num(c["CREndBG"]), num(c["CREndIOB"]), num(c["CRCarbs"]), num(c["CRInsulin"]))
        },
        csfGlucose = (d["CSFGlucoseData"] as List<*>).map { bg(it as Document) },
        isfGlucose = (d["ISFGlucoseData"] as List<*>).map { bg(it as Document) },
        basalGlucose = (d["basalGlucoseData"] as List<*>).map { bg(it as Document) },
    )

    private fun check(prepFile: String, inputFile: String, pumpFile: String, expectedFile: String) {
        val pump = read(pumpFile)
        val out = AutotuneCore.tune(prepped(read(prepFile)), profile(read(inputFile)), profile(pump), limits(pump), ZoneId.of("GMT+2"))
        val expected = profile(read(expectedFile))
        assertEquals(expected.isf, out.isf, 0.0)
        assertEquals(expected.ic, out.ic, 0.0)
        for (i in 0..23) assertEquals("hour $i", expected.basal[i], out.basal[i], 0.0)
    }

    @Test fun test1() = check("test1/autotune.2022-05-21.json", "test1/profile.pump.json", "test1/profile.pump.json", "test1/aapsorefprofile.json")
    @Test fun test4() = check("test4/autotune.2022-05-30.json", "test4/profile.2022-05-30.json", "test4/profile.pump.json", "test4/newprofile.2022-05-30.json")
}
