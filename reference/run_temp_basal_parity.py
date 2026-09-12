"""Execute unchanged pinned AAPS temporary-basal conversion with explicit stubs."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--java", required=True)
parser.add_argument("--kotlin-lib", required=True)
args = parser.parse_args()
manifest = json.loads((root / "aaps/manifest.json").read_text())
for name, entry in manifest["files"].items():
    if hashlib.sha256((root / "aaps" / name).read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"Reference hash mismatch: {name}")
source = (root / "aaps/AutotuneIob.kt").read_text()
a = source.index("    private fun convertToBoluses(tbr: TB")
b = source.index("    fun BS.toJson", a)
section = source[a:b]
extension = (root / "aaps/TemporaryBasalExtension.kt").read_text()
a = extension.index("val TB.durationInMinutes")
b = extension.index("\n", extension.index("get() =", a))
extension = extension[a:b]
wrapper = '''import kotlin.math.ceil
import app.aaps.core.interfaces.utils.Round
import app.aaps.core.data.time.T
class IDs {var nightscoutId:String?="synthetic"}
data class TB(val timestamp:Long,val duration:Long,val rate:Double,val isAbsolute:Boolean,val ids:IDs=IDs())
data class BS(val ids:IDs,val timestamp:Long,val amount:Double,val type:Type) {enum class Type {NORMAL}}
class Profile(val rate:Double) {fun getBasal(timestamp:Long):Double=rate}
''' + extension + '\n' + section + '''
fun main() {
while(true) {
val line=readlnOrNull() ?: break
val p=line.split(",")
val result=convertToBoluses(TB(p[0].toLong(),p[1].toLong(),p[2].toDouble(),p[3].toBoolean()),Profile(p[4].toDouble()),Profile(p[5].toDouble()))
println(result.joinToString(";"){"${it.timestamp},${it.amount}"})
}
}
'''
spec = importlib.util.spec_from_file_location("research_temp", root / "research/temp_basal_component.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [(1700000000000, duration, rate, absolute, basal, tuned)
         for duration in (0, 59_999, 60_000, 299_999, 300_000, 301_000, 659_999, 1_800_001, 3_600_000)
         for absolute, rates in ((True, (0.0, 0.0005, 0.9995, 1.5, 3.0)), (False, (0.0, 50.0, 100.0, 150.0, 200.0)))
         for rate in rates for basal, tuned in ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 1.2))]
with tempfile.TemporaryDirectory(prefix="aaps-temp-parity-") as temp:
    path = Path(temp)
    (path / "Runner.kt").write_text(wrapper)
    env = dict(os.environ, JAVA_HOME=str(Path(args.java).resolve().parent.parent))
    subprocess.run([args.java, "-cp", str(Path(args.kotlin_lib) / "*"), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                    str(path / "Runner.kt"), str(root / "aaps/Round.kt"), str(root / "aaps/T.kt"),
                    "-include-runtime", "-d", str(path / "runner.jar")], env=env, check=True)
    lines = [f"{ts},{duration},{rate},{str(absolute).lower()},{basal},{tuned}" for ts, duration, rate, absolute, basal, tuned in cases]
    result = subprocess.run([args.java, "-jar", str(path / "runner.jar")], input="\n".join(lines)+"\n", text=True, capture_output=True, check=True)
    outputs = result.stdout.splitlines()
    if len(outputs) != len(cases):
        raise AssertionError("Missing Kotlin results")
    maximum = 0.0
    contributions = 0
    for case, line in zip(cases, outputs):
        expected = [(int(p.split(",")[0]), float(p.split(",")[1])) for p in line.split(";")] if line else []
        actual = module.temp_basal_contributions(*case)
        if len(expected) != len(actual):
            raise AssertionError((case, expected, actual))
        for (tx, x), (ty, y) in zip(expected, actual):
            if tx != ty or not math.isfinite(y) or abs(x-y) > 1e-10:
                raise AssertionError((case, expected, actual))
            maximum = max(maximum, abs(x-y))
            contributions += 1
    evidence = {"reference_commit": manifest["commit"], "component": "AutotuneIob temporary-basal convertToBoluses section",
                "cases": len(cases), "contributions_compared": contributions,
                "maximum_absolute_amount_difference": maximum, "timestamp_differences": 0,
                "scope": "One already-resolved segment; not splitting, profile resolution, pump confirmation, cancellation, total IOB or clinical validation.",
                "python_sha256": hashlib.sha256((root / "research/temp_basal_component.py").read_bytes()).hexdigest(),
                "kotlin_section_sha256": hashlib.sha256(section.encode()).hexdigest()}
    (root / "temp-basal-parity-result.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps(evidence, indent=2))
