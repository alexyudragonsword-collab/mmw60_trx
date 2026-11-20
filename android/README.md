# mmw60 的手机外壳（Android）

同一个页面的第三个宿主：桌面与浏览器由 `mmw60-gui` 提供 `src/mmw60/webui/www`，这个 APK 把同一批文件当 assets 装进去，
页面里的 `api()` 改走 `window.host` → `mmw60.appbridge.call(route, json)`。Python 是包里自带的 CPython 3.10（Chaquopy），
全部在本机算，**不申请任何权限**，不联网。

Kotlin 只有一个 Activity，不承载任何功能：一个功能 = `webhost.Api` 后面的一个 Python 函数 + 页面里的一处渲染。

## 构建

Java 17、Python 3.10、Android SDK、Gradle 8.2：

```bash
gradle -p android :app:assembleDebug        # -> android/app/build/outputs/apk/debug/app-debug.apk
python android/tools/check_apk.py android/app/build/outputs/apk/debug/app-debug.apk src/mmw60/webui/www android/phone-stack.txt
```

库以源码进包（Gradle 的 Python 源目录指向 `../../src`），不经过 pip，所以改了 Python 重新构建就生效，没有要记得重打的 sdist。
CI 里是 `.github/workflows/android.yml`：构建、读包里到底有什么、再在模拟器上跑两条设备测试；产物 `mmw60-debug-apk` 可侧载。

## 版本这一组要一起动

| 项 | 取值 | 为什么 |
|---|---|---|
| Chaquopy / AGP / Kotlin / Gradle | 15.0.1 / 8.1.4 / 1.9.24 / 8.2 | 姊妹库（array_tx、polar_tx、pll_simulator）构建通过的那一组 |
| Python | 3.10 | Chaquopy 仓库里有 scipy wheel 的最新 Python；Gradle、两个工作流三处写的必须相同（测试守着） |
| numpy / scipy | `android/phone-stack.txt` | Chaquopy 给 Python 3.10 的版本，**比 `pyproject.toml` 声明的桌面下限旧** |

最后一行是这个外壳与姊妹库不同的地方：桌面声明 numpy ≥ 1.26、scipy ≥ 1.11，手机上拿不到。所以：

- 手机桥这条路径不导入 matplotlib，也不需要 numba（`tests/test_android.py` 在一个导入它们就报错的解释器里把四份报告读了一遍）；
- CI 的 `test-phone-stack` 作业在 Python 3.10 上**只装 `phone-stack.txt` 里的版本**，跑宿主 / 仓库 / 计算层的测试、每个任务的试算档和自检——
  声明了却不测的下限等于没声明（polar_tx 在真机上栽过）；
- 改 `phone-stack.txt` 一行，APK 和那个作业一起动。

## 设备上怎么知道算得对

`mmw60.appbridge.self_check()`：经页面用的同一条路由读四份随包报告（数据文件读得到），再把同台表的解析列在本机重算一遍，
与随包基线逐数比（`guiutil.analytic_agreement`，上限 1e-9）。`python -m mmw60.appbridge [--jobs]` 在任何机器上都能跑。
设备测试（`app/src/androidTest/.../OnDeviceTest.kt`）只断言它的结论，外加一条“页面经桥把表画出来了”。
工作流按**精确条数**核对设备测试真的跑了，并把设备说的话（解释器、numpy、scipy、偏差、耗时）印在日志末尾。

## 没有验证的

见 `ROADMAP.md` F 与 `cairn/gui.md` §7：真机（只在 x86_64 模拟器上跑过）、arm64 的数值、手机上各任务要多久。
