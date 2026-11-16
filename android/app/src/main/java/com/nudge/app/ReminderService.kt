package com.nudge.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.webkit.CookieManager
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.concurrent.Executors

class ReminderService : Service() {
    private data class ReminderEvent(
        val key: String,
        val title: String,
        val deadline: Long?,
        val done: Boolean,
    )

    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val prefs: SharedPreferences by lazy {
        getSharedPreferences("nudge_alerts", MODE_PRIVATE)
    }
    private val tick = object : Runnable {
        override fun run() {
            executor.execute { refresh() }
            handler.postDelayed(this, POLL_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        createChannels()
        val notification = buildOngoing("正在连接 Nudge…")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(ONGOING_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(ONGOING_ID, notification)
        }
        handler.post(tick)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun refresh() {
        val events = fetchEvents()
        if (events == null) {
            updateOngoing("暂时连不上云端，稍后重试")
            return
        }
        val now = System.currentTimeMillis()
        val upcoming = events
            .filter { !it.done && it.deadline != null && it.deadline > now }
            .sortedBy { it.deadline }
        val nearest = upcoming.firstOrNull()
        if (nearest == null) {
            updateOngoing("暂无进行中的截止事项")
        } else {
            val minutes = ((nearest.deadline!! - now) / 60_000).coerceAtLeast(0)
            updateOngoing("最近截止：${nearest.title} · ${minutes} 分钟后")
        }
        for (event in upcoming) {
            val left = event.deadline!! - now
            if (left in 1..THIRTY_MIN && !alreadyAlerted(event)) {
                alert(event)
                markAlerted(event)
            }
        }
    }

    private fun fetchEvents(): List<ReminderEvent>? {
        val cookie = CookieManager.getInstance()
            .getCookie(BuildConfig.NUDGE_URL)
            ?.split(";")
            ?.map { it.trim() }
            ?.firstOrNull { it.startsWith("nudge_session=") }
            ?: return null
        return try {
            val connection = (URL(BuildConfig.NUDGE_URL + "/api/events")
                .openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 8000
                readTimeout = 8000
                setRequestProperty("Cookie", cookie)
            }
            val body = connection.inputStream.bufferedReader().use { it.readText() }
            connection.disconnect()
            parse(body)
        } catch (error: Exception) {
            null
        }
    }

    private fun parse(body: String): List<ReminderEvent> {
        val array = JSONArray(body)
        val result = mutableListOf<ReminderEvent>()
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            result.add(
                ReminderEvent(
                    key = item.optString("dedup_key").ifBlank { item.optString("id") },
                    title = item.optString("title").ifBlank { "未命名事项" },
                    deadline = parseDeadline(item.optString("deadline_end")),
                    done = !item.isNull("done_at") && item.optString("done_at").isNotBlank(),
                )
            )
        }
        return result
    }

    private fun parseDeadline(raw: String): Long? {
        if (raw.isBlank()) return null
        val formats = listOf(
            "yyyy-MM-dd'T'HH:mm:ssXXX",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-dd",
        )
        for (pattern in formats) {
            try {
                val date = SimpleDateFormat(pattern, Locale.CHINA).parse(raw) ?: continue
                if (pattern == "yyyy-MM-dd") {
                    return Calendar.getInstance().apply {
                        time = date
                        set(Calendar.HOUR_OF_DAY, 23)
                        set(Calendar.MINUTE, 59)
                        set(Calendar.SECOND, 0)
                    }.timeInMillis
                }
                return date.time
            } catch (error: Exception) {
                continue
            }
        }
        return null
    }

    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ONGOING, "Nudge 常驻状态", NotificationManager.IMPORTANCE_LOW)
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ALERT, "截止提醒", NotificationManager.IMPORTANCE_HIGH)
        )
    }

    private fun buildOngoing(text: String): Notification {
        val intent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ONGOING)
            .setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle("Nudge")
            .setContentText(text)
            .setContentIntent(intent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateOngoing(text: String) {
        getSystemService(NotificationManager::class.java).notify(ONGOING_ID, buildOngoing(text))
    }

    private fun alert(event: ReminderEvent) {
        val minutes = ((event.deadline!! - System.currentTimeMillis()) / 60_000).coerceAtLeast(1)
        val notification = Notification.Builder(this, CHANNEL_ALERT)
            .setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle("还有 $minutes 分钟截止")
            .setContentText(event.title)
            .setAutoCancel(true)
            .build()
        getSystemService(NotificationManager::class.java).notify(event.key.hashCode(), notification)
    }

    private fun alertKey(event: ReminderEvent) = "${event.key}@${event.deadline}"

    private fun alreadyAlerted(event: ReminderEvent): Boolean =
        prefs.getBoolean(alertKey(event), false)

    private fun markAlerted(event: ReminderEvent) {
        prefs.edit().putBoolean(alertKey(event), true).apply()
    }

    companion object {
        private const val CHANNEL_ONGOING = "nudge_ongoing"
        private const val CHANNEL_ALERT = "nudge_alert"
        private const val ONGOING_ID = 1001
        private const val POLL_MS = 60_000L
        private const val THIRTY_MIN = 30 * 60_000L
    }
}