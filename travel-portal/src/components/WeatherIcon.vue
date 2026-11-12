<script setup lang="ts">
/** 天气图标：内联 SVG 自绘，替代 emoji，视觉更统一、可随主题配色。
 *  用法：<WeatherIcon weather="小雨" :size="28" />；night=true 时晴天显示月亮。
 */
import { computed } from 'vue'
import { classify, type WeatherKind } from './weatherKind'

const props = withDefaults(defineProps<{
  weather?: string
  night?: boolean
  size?: number
}>(), {
  weather: '',
  night: false,
  size: 40,
})

const kind = computed<WeatherKind>(() => classify(props.weather, props.night))

/** 底层天体：太阳或月亮 */
const base = computed<'sun' | 'moon' | 'none'>(() => {
  if (kind.value === 'sun') return 'sun'
  if (kind.value === 'moon') return 'moon'
  if (kind.value === 'partly') return props.night ? 'moon' : 'sun'
  return 'none'
})

/** 是否叠加云层 */
const hasCloud = computed(() => ['partly', 'overcast', 'rain', 'heavyrain', 'thunder', 'snow', 'fog'].includes(kind.value))

/** 云层偏移：晴天为主，云在后；阴雨天云在前 */
const cloudShift = computed(() => (kind.value === 'partly' ? 4 : 0))

let seq = 0
const uid = `wgi${++seq}`
</script>

<template>
  <svg
    class="wicon"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    :style="{ width: size + 'px', height: size + 'px' }"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient :id="`${uid}-sun`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#FFD469" />
        <stop offset="100%" stop-color="#FFA62B" />
      </linearGradient>
      <linearGradient :id="`${uid}-cloud`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#FFFFFF" />
        <stop offset="100%" stop-color="#DCE6EE" />
      </linearGradient>
      <linearGradient :id="`${uid}-cloud-dark`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#E7EDF3" />
        <stop offset="100%" stop-color="#BCCBD8" />
      </linearGradient>
    </defs>

    <!-- 太阳 -->
    <g v-if="base === 'sun'">
      <g stroke="#FFC44D" stroke-width="2.6" stroke-linecap="round">
        <line x1="24" y1="3.5" x2="24" y2="9" />
        <line x1="24" y1="39" x2="24" y2="44.5" />
        <line x1="3.5" y1="24" x2="9" y2="24" />
        <line x1="39" y1="24" x2="44.5" y2="24" />
        <line x1="9.4" y1="9.4" x2="13" y2="13" />
        <line x1="35" y1="35" x2="38.6" y2="38.6" />
        <line x1="38.6" y1="9.4" x2="35" y2="13" />
        <line x1="13" y1="35" x2="9.4" y2="38.6" />
      </g>
      <circle cx="24" cy="24" r="9.4" :fill="`url(#${uid}-sun)`" />
      <circle cx="20.5" cy="20.5" r="3" fill="#FFF3D0" opacity=".55" />
    </g>

    <!-- 月亮 -->
    <g v-else-if="base === 'moon'">
      <path
        d="M33.5 5.5A18.5 18.5 0 1 0 42 27.8 15.6 15.6 0 0 1 33.5 5.5Z"
        fill="#F5F7D8"
        stroke="#E3E7C0"
        stroke-width="1"
        stroke-linejoin="round"
      />
      <circle cx="17" cy="30" r="2" fill="#E7EBC4" opacity=".8" />
      <circle cx="22" cy="36" r="1.4" fill="#E7EBC4" opacity=".6" />
    </g>

    <!-- 云 -->
    <g v-if="hasCloud" :transform="`translate(0 ${cloudShift})`">
      <path
        d="M14 39h19.5a8.6 8.6 0 0 0 1-17.1A12.2 12.2 0 0 0 11.6 23.6 7.7 7.7 0 0 0 14 39z"
        :fill="kind === 'overcast' || kind === 'rain' || kind === 'heavyrain' || kind === 'thunder' ? `url(#${uid}-cloud-dark)` : `url(#${uid}-cloud)`"
      />
    </g>

    <!-- 雨 -->
    <g v-if="kind === 'rain' || kind === 'heavyrain'">
      <g stroke="#4FA3E8" stroke-width="2.4" stroke-linecap="round">
        <line x1="17" y1="40" x2="15.4" y2="45" />
        <line x1="24" y1="40" x2="22.4" y2="45" />
        <line x1="31" y1="40" x2="29.4" y2="45" />
      </g>
      <g v-if="kind === 'heavyrain'" stroke="#3B86D6" stroke-width="2.2" stroke-linecap="round">
        <line x1="20.5" y1="34" x2="19.2" y2="38" />
        <line x1="27.5" y1="34" x2="26.2" y2="38" />
      </g>
    </g>

    <!-- 雷 -->
    <g v-if="kind === 'thunder'">
      <path d="M25 33.5 20 41.5h4.2l-1.6 5.4 6.2-8h-4.3l2.4-5.4Z" fill="#FFC53D" stroke="#F0A92B" stroke-width=".8" stroke-linejoin="round" />
    </g>

    <!-- 雪 -->
    <g v-if="kind === 'snow'">
      <g stroke="#9FD4F0" stroke-width="2" stroke-linecap="round">
        <line x1="17" y1="41" x2="17" y2="45" />
        <line x1="15.2" y1="42" x2="18.8" y2="44" />
        <line x1="18.8" y1="42" x2="15.2" y2="44" />
        <line x1="24" y1="41.5" x2="24" y2="45.5" />
        <line x1="22.2" y1="42.5" x2="25.8" y2="44.5" />
        <line x1="25.8" y1="42.5" x2="22.2" y2="44.5" />
        <line x1="31" y1="41" x2="31" y2="45" />
        <line x1="29.2" y1="42" x2="32.8" y2="44" />
        <line x1="32.8" y1="42" x2="29.2" y2="44" />
      </g>
    </g>

    <!-- 雾 -->
    <g v-if="kind === 'fog'">
      <g stroke="#B7C6D2" stroke-width="2.4" stroke-linecap="round">
        <line x1="13" y1="39" x2="35" y2="39" />
        <line x1="17" y1="43" x2="31" y2="43" />
      </g>
    </g>
  </svg>
</template>

<style scoped>
.wicon { display: block; flex: none; }
</style>
