package app.bganalyzer.domain

enum class SuggestionKind { BASAL, CARB_RATIO }
enum class Confidence { LOW, MEDIUM, HIGH }

/**
 * One advisory idea for one time of day. It is never applied by the app: the user decides.
 * [changePct] is the suggested change to the setting's value (basal rate or carb ratio in g/U), already capped.
 * For a basal suggestion [fromUph]/[toUph] give the absolute rates.
 */
data class Suggestion(
    val kind: SuggestionKind,
    val startHour: Int,
    val endHour: Int,
    /** True when the suggestion gives more insulin (higher basal, lower carb ratio number). */
    val moreInsulin: Boolean,
    val changePct: Int,
    val fromUph: Double?,
    val toUph: Double?,
    val confidence: Confidence,
    /** Plain-language facts behind the suggestion. */
    val evidence: List<String>,
    /** Extra line with absolute values, e.g. the carb ratio before and after. */
    val detail: String? = null,
)

/** A block where a rule held an increase back, with the reason. Shown so a missing suggestion is explained. */
data class Held(val kind: SuggestionKind, val startHour: Int, val endHour: Int, val reason: String)

data class SuggestionResult(val suggestions: List<Suggestion>, val held: List<Held>)

/**
 * Turns the Patterns observations into advisory suggestions with guard rails. Pure code.
 * Guard rails: each change is capped per step, lows in a block stop insulin increases for that block only,
 * and a number is shown only with enough days or meals and agreement between them.
 */
object Suggestions {
    const val MAX_STEP_PCT = 20
    const val MAX_BASAL_STEP_UPH = 0.5
    const val MIN_CHANGE_PCT = 10
    /** Share of days in a block with a low reading (or any very low) that stops increases there. */
    const val LOW_DAY_SHARE = 0.10
    const val AGREEMENT = 0.6
    private const val CARB_STEP_PCT = 10
    /** Median drift beyond this many mg/dL per hour counts. */
    private const val DRIFT_MIN = 8.0

    fun generate(
        blocks: List<BlockStats>,
        meals: List<MealBlockStats>,
        basal: BasalComparisonResult?,
        drift: List<DriftBlockStats> = emptyList(),
        /** Profile basal (U/h) per block start hour, so drift suggestions work without loop data. */
        scheduled: Map<Int, Double> = emptyMap(),
        settings: ProfileSettings = ProfileSettings.NONE,
    ): SuggestionResult {
        val out = ArrayList<Suggestion>()
        val held = ArrayList<Held>()
        fun lowsIn(b: BlockStats?) = b != null && b.days > 0 && (b.veryLowDays > 0 || b.lowDays.toDouble() / b.days >= LOW_DAY_SHARE)

        basal?.blocks?.forEach { bb ->
            val g = blocks.firstOrNull { it.startHour == bb.startHour }
            if (!bb.enoughDays || bb.avgScheduled <= 0) return@forEach
            val above = bb.abovePct / 100; val below = bb.belowPct / 100
            val highShare = g?.timeInRange?.let { (it.highPct + it.veryHighPct) / 100 } ?: 0.0
            when {
                above >= AGREEMENT && bb.changePct >= MIN_CHANGE_PCT -> {
                    if (lowsIn(g)) { held += Held(SuggestionKind.BASAL, bb.startHour, bb.endHour, "the loop runs above profile but glucose went low on ${g!!.lowDays} of ${g.days} days"); return@forEach }
                    if (highShare < 0.25) { held += Held(SuggestionKind.BASAL, bb.startHour, bb.endHour, "the loop runs above profile but glucose is mostly in range here"); return@forEach }
                    val pct = bb.changePct.toInt().coerceAtMost(MAX_STEP_PCT)
                    val to = minOf(bb.avgScheduled * (1 + pct / 100.0), bb.avgScheduled + MAX_BASAL_STEP_UPH)
                    out += basalSuggestion(bb, true, to, above, g, conf(bb.days, above))
                }
                below >= AGREEMENT && bb.changePct <= -MIN_CHANGE_PCT -> {
                    val pct = (-bb.changePct).toInt().coerceAtMost(MAX_STEP_PCT)
                    val to = maxOf(bb.avgScheduled * (1 - pct / 100.0), bb.avgScheduled - MAX_BASAL_STEP_UPH)
                    out += basalSuggestion(bb, false, to, below, g, conf(bb.days, below))
                }
            }
        }

        meals.forEach { m ->
            if (!m.enoughMeals) return@forEach
            val g = blocks.firstOrNull { it.startHour == m.startHour }
            val lowShare = m.lowWithin4h.toDouble() / m.meals
            val highShare = if (m.withReading2h >= PostMeal.MIN_MEALS) m.highAt2h.toDouble() / m.withReading2h else 0.0
            when {
                lowShare >= 0.3 -> out += Suggestion(
                    SuggestionKind.CARB_RATIO, m.startHour, m.endHour, false, CARB_STEP_PCT, null, null, conf(m.meals, lowShare),
                    listOf("${m.lowWithin4h} of ${m.meals} meals were followed by a low within 4 h", "Suggestion: less insulin per carb (raise the carb ratio number by about $CARB_STEP_PCT%)"),
                    crDetail(settings, m.startHour, m.endHour, false),
                )
                highShare >= AGREEMENT -> {
                    if (lowsIn(g) || lowShare >= LOW_DAY_SHARE) {
                        held += Held(SuggestionKind.CARB_RATIO, m.startHour, m.endHour, "glucose is high 2 h after meals but lows also happen in this time of day")
                    } else out += Suggestion(
                        SuggestionKind.CARB_RATIO, m.startHour, m.endHour, true, CARB_STEP_PCT, null, null, conf(m.withReading2h, highShare),
                        listOf("${m.highAt2h} of ${m.withReading2h} meals were above the high limit 2 h later", "Suggestion: more insulin per carb (lower the carb ratio number by about $CARB_STEP_PCT%)"),
                        crDetail(settings, m.startHour, m.endHour, true),
                    )
                }
            }
        }
        // Glucose drifting on its own with no food or manual insulin points at basal, with or without a loop.
        drift.forEach { d ->
            if (!d.enoughDays) return@forEach
            val g = blocks.firstOrNull { it.startHour == d.startHour }
            val sched = scheduled[d.startHour] ?: return@forEach
            if (sched <= 0) return@forEach
            val rising = d.medianSlopeMgdlPerHour >= DRIFT_MIN && d.risingDays.toDouble() / d.days >= AGREEMENT
            val falling = d.medianSlopeMgdlPerHour <= -DRIFT_MIN && d.fallingDays.toDouble() / d.days >= AGREEMENT
            if (!rising && !falling) return@forEach
            val agree = (if (rising) d.risingDays else d.fallingDays).toDouble() / d.days
            // With a known sensitivity, size the step from the drift (mg/dL per hour / mg/dL per U = U/h); else use fixed steps.
            val isf = settings.isfMgdlAt(d.startHour)
            val pct = if (isf != null && isf > 0) {
                Math.round(kotlin.math.abs(d.medianSlopeMgdlPerHour) / isf / sched * 100).toInt().coerceIn(5, MAX_STEP_PCT)
            } else if (kotlin.math.abs(d.medianSlopeMgdlPerHour) >= 15) MAX_STEP_PCT else MIN_CHANGE_PCT
            val fact = "With no food or manual insulin, glucose ${if (rising) "rose" else "fell"} on ${if (rising) d.risingDays else d.fallingDays} of ${d.days} quiet days (median ${"%+.0f".format(d.medianSlopeMgdlPerHour)} mg/dL per hour)"
            val existing = out.indexOfFirst { it.kind == SuggestionKind.BASAL && it.startHour == d.startHour }
            if (existing >= 0) {
                val e = out[existing]
                if (e.moreInsulin == rising) out[existing] = e.copy(evidence = e.evidence + fact, confidence = maxOf(e.confidence, conf(d.days, agree)))
                else {
                    out.removeAt(existing)
                    held += Held(SuggestionKind.BASAL, d.startHour, d.endHour, "loop behaviour and drift without food point in opposite directions")
                }
                return@forEach
            }
            if (held.any { it.kind == SuggestionKind.BASAL && it.startHour == d.startHour }) return@forEach
            if (rising && lowsIn(g)) { held += Held(SuggestionKind.BASAL, d.startHour, d.endHour, "glucose drifts up without food but lows also happen in this time of day"); return@forEach }
            val to = if (rising) minOf(sched * (1 + pct / 100.0), sched + MAX_BASAL_STEP_UPH) else maxOf(sched * (1 - pct / 100.0), sched - MAX_BASAL_STEP_UPH)
            out += Suggestion(SuggestionKind.BASAL, d.startHour, d.endHour, rising, pct, sched, Math.round(to * 20) / 20.0, conf(d.days, agree), listOf(fact))
        }
        return SuggestionResult(out.sortedWith(compareBy({ it.startHour }, { it.kind })), held)
    }

    private fun crDetail(settings: ProfileSettings, start: Int, end: Int, more: Boolean): String? {
        val cr = settings.carbRatioAt(start) ?: return null
        val to = if (more) cr * (1 - CARB_STEP_PCT / 100.0) else cr * (1 + CARB_STEP_PCT / 100.0)
        val note = if (settings.carbRatio.map { it.rateUph }.distinct().size > 1) " (profile value at $start:00)" else ""
        return "Profile carb ratio ${"%.1f".format(cr)} -> ${"%.1f".format(to)} g/U$note"
    }

    private fun conf(n: Int, agreement: Double) = when {
        n >= 14 && agreement >= 0.8 -> Confidence.HIGH
        n >= 8 && agreement >= 0.7 -> Confidence.MEDIUM
        else -> Confidence.LOW
    }

    private fun basalSuggestion(bb: BasalBlockStats, more: Boolean, to: Double, agreement: Double, g: BlockStats?, c: Confidence) = Suggestion(
        SuggestionKind.BASAL, bb.startHour, bb.endHour, more,
        kotlin.math.abs((to / bb.avgScheduled - 1) * 100).let { Math.round(it).toInt() },
        bb.avgScheduled, Math.round(to * 20) / 20.0, c,
        listOfNotNull(
            "The loop ran ${if (more) "above" else "below"} the profile for ${Math.round(agreement * 100)}% of the time over ${bb.days} days (average ${"%.2f".format(bb.avgActual)} vs ${"%.2f".format(bb.avgScheduled)} U/h)",
            g?.takeIf { it.days > 0 }?.let { "Glucose in this time of day: ${Math.round(it.timeInRange.inRangePct)}% in range, ${it.lowDays} of ${it.days} days with a low" },
        ),
    )
}
