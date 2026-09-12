"""Execute the pinned upstream Kotlin basal section; compare research Python output.
Requires --java JAVA --kotlin-lib PATH. No medical data or application imports.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--java', required=True)
parser.add_argument('--kotlin-lib', required=True)
args = parser.parse_args()
manifest = json.loads((root / 'aaps/manifest.json').read_text())
for name, entry in manifest['files'].items():
    assert hashlib.sha256((root / 'aaps' / name).read_bytes()).hexdigest() == entry['sha256'], name
source = (root / 'aaps/AutotuneCore.kt').read_text()
a = source.index('        val hourlyBasalProfile = basalProfile')
b = source.index('        basalProfile = newHourlyBasalProfile', a)
section = source[a:b]
wrapper = '''import java.util.Calendar
import java.util.TimeZone
import app.aaps.core.interfaces.utils.Round
data class BG(val date:Long,val deviation:Double)
data class Previous(val basalUnTuned:IntArray)
fun log(text:String) {}
fun run(basalProfile:DoubleArray,pumpBasalProfile:DoubleArray,isf:Double,autotuneMin:Double,autotuneMax:Double,basalGlucose:List<BG>):DoubleArray {
val previousAutotune=Previous(IntArray(24))
''' + section + '''
return newHourlyBasalProfile
}
fun main() {
while(true) {
val previous=readlnOrNull() ?: break
val pump=readln()
val params=readln().split(",").map{it.toDouble()}
TimeZone.setDefault(TimeZone.getTimeZone(readln()))
val records=readln()
val glucose=if(records.isEmpty()) emptyList() else records.split(";").map{val p=it.split(",");BG(p[0].toLong(),p[1].toDouble())}
println(run(previous.split(",").map{it.toDouble()}.toDoubleArray(),pump.split(",").map{it.toDouble()}.toDoubleArray(),params[0],params[1],params[2],glucose).joinToString(","))
}
}
'''
spec = importlib.util.spec_from_file_location('research_basal', root / 'research/basal_component.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rng = random.Random(421)
cases = []
for zone in ('UTC', 'Europe/London'):
    for day in ('2026-01-10', '2026-03-29', '2026-10-25'):
        base = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        for mode in range(12):
            pump = [round(rng.uniform(0.15, 2.0), 3) for _ in range(24)]
            previous = list(pump) if mode < 8 else [round(x * 1.1, 3) for x in pump]
            glucose = [] if mode == 0 else [(base + i * 300000, (25 if mode == 1 else -25 if mode == 2 else rng.uniform(-40, 40))) for i in range(288)]
            cases.append((previous, pump, 45.0, 0.7, 1.2, glucose, zone))
with tempfile.TemporaryDirectory(prefix='aaps-basal-parity-') as temp:
    path = Path(temp)
    (path / 'Runner.kt').write_text(wrapper)
    env = dict(os.environ, JAVA_HOME=str(Path(args.java).resolve().parent.parent))
    subprocess.run([args.java, '--enable-native-access=ALL-UNNAMED', '-cp', str(Path(args.kotlin_lib) / '*'), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                    str(path / 'Runner.kt'), str(root / 'aaps/Round.kt'), '-include-runtime', '-d', str(path / 'runner.jar')], env=env, check=True)
    lines = []
    for previous, pump, isf, lo, hi, glucose, zone in cases:
        lines.extend([','.join(map(str, previous)), ','.join(map(str, pump)), f'{isf},{lo},{hi}', zone, ';'.join(f'{ms},{dev}' for ms, dev in glucose)])
    result = subprocess.run([args.java, '--enable-native-access=ALL-UNNAMED', '-jar', str(path / 'runner.jar')], input='\n'.join(lines) + '\n', text=True, capture_output=True, check=True)
    outputs = result.stdout.splitlines()
    assert len(outputs) == len(cases)
    maximum = 0
    for case, line in zip(cases, outputs):
        expected = list(map(float, line.split(',')))
        actual = module.tune_basal(*case)
        error = max(abs(x - y) for x, y in zip(expected, actual))
        maximum = max(maximum, error)
        assert error <= 1e-10, (case[-1], expected, actual)
    evidence = {'reference_commit': manifest['commit'], 'component': 'AutotuneCore basal section only',
                'cases': len(cases), 'compared_hourly_values': 24 * len(cases), 'maximum_absolute_difference': maximum,
                'scope': 'Synthetic preclassified deviations; not profile resolution, insulin reconstruction, prep, or end-to-end validation.',
                'python_sha256': hashlib.sha256((root / 'research/basal_component.py').read_bytes()).hexdigest(),
                'kotlin_section_sha256': hashlib.sha256(section.encode()).hexdigest()}
    (root / 'basal-parity-result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))