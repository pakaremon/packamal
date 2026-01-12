#!/bin/bash

# Default: run all packages
NUM_SAMPLES=""
RANGE_START=""
RANGE_END=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n)
            NUM_SAMPLES="$2"
            # Check if it's a range (contains :)
            if [[ "$NUM_SAMPLES" == *:* ]]; then
                RANGE_START="${NUM_SAMPLES%%:*}"
                RANGE_END="${NUM_SAMPLES##*:}"
                
                # Validate range format
                if ! [[ "$RANGE_START" =~ ^[0-9]+$ ]] || ! [[ "$RANGE_END" =~ ^[0-9]+$ ]]; then
                    echo "Error: Range must be in format 'start:end' where both are positive integers"
                    echo "Usage: $0 [-n <number|start:end>]"
                    echo "  -n <number>: Run only the first N packages"
                    echo "  -n <start:end>: Run packages from index start to end (end is exclusive, like Python slicing)"
                    exit 1
                fi
                
                # Validate range values
                if [ "$RANGE_START" -ge "$RANGE_END" ]; then
                    echo "Error: Range start ($RANGE_START) must be less than end ($RANGE_END)"
                    exit 1
                fi
                
                NUM_SAMPLES=""  # Clear NUM_SAMPLES since we're using range
            elif ! [[ "$NUM_SAMPLES" =~ ^[0-9]+$ ]]; then
                echo "Error: -n requires a positive integer or range (start:end)"
                echo "Usage: $0 [-n <number|start:end>]"
                echo "  -n <number>: Run only the first N packages"
                echo "  -n <start:end>: Run packages from index start to end (end is exclusive, like Python slicing)"
                exit 1
            fi
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-n <number|start:end>]"
            echo "  -n <number>: Run only the first N packages (default: all)"
            echo "  -n <start:end>: Run packages from index start to end (end is exclusive, like Python slicing)"
            echo "                 Example: -n 10:20 runs packages at indices 10-19"
            echo "  -h, --help: Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-n <number|start:end>]"
            echo "  -n <number>: Run only the first N packages"
            echo "  -n <start:end>: Run packages from index start to end (end is exclusive, like Python slicing)"
            exit 1
            ;;
    esac
done

API_URL="http://4.249.47.62/api/v1/analyze/"
TOKEN="n7wTepxaEInxBEOjlbXNdQccOPbJ4pFVC6WcsNLoOfIikXtS18MhkKuuuIUgvrHB"
PACKAGES=(
  "pkg:npm/graphql@16.8.1"           # 96
  # 1–10
  "pkg:npm/lodash@4.17.21"        # 1
  "pkg:npm/express@4.18.2"        # 2
  "pkg:npm/react@18.2.0"          # 3
  "pkg:npm/react-dom@18.2.0"      # 4
  "pkg:npm/axios@1.6.2"           # 5
  "pkg:npm/moment@2.29.4"         # 6
  "pkg:npm/dayjs@1.11.10"         # 7
  "pkg:npm/debug@4.3.4"           # 8
  "pkg:npm/dotenv@16.3.1"         # 9
  "pkg:npm/cors@2.8.5"            # 10

  # 11–20
  "pkg:npm/mongoose@7.6.3"        # 11
  "pkg:npm/jsonwebtoken@9.0.2"    # 12
  "pkg:npm/bcrypt@5.1.1"          # 13
  "pkg:npm/body-parser@1.20.2"    # 14
  "pkg:npm/morgan@1.10.0"         # 15
  "pkg:npm/chalk@4.1.2"           # 16
  "pkg:npm/nodemon@3.0.2"         # 17
  "pkg:npm/uuid@9.0.1"            # 18
  "pkg:npm/ws@8.14.2"              # 19
  "pkg:npm/socket.io@4.7.2"       # 20

  # 21–30
  "pkg:npm/yargs@17.7.2"          # 21
  "pkg:npm/inquirer@9.2.12"       # 22
  "pkg:npm/commander@11.1.0"      # 23
  "pkg:npm/node-fetch@3.3.2"      # 24
  "pkg:npm/got@13.0.0"            # 25
  "pkg:npm/cheerio@1.0.0-rc.12"   # 26
  "pkg:npm/sharp@0.33.0"          # 27
  "pkg:npm/joi@17.11.0"           # 28
  "pkg:npm/zod@3.22.4"            # 29
  "pkg:npm/ajv@8.12.0"            # 30

  # 31–40
  "pkg:npm/eslint@8.55.0"         # 31
  "pkg:npm/prettier@3.1.0"        # 32
  "pkg:npm/typescript@5.3.2"      # 33
  "pkg:npm/ts-node@10.9.2"        # 34
  "pkg:npm/vite@5.0.4"            # 35
  "pkg:npm/webpack@5.89.0"        # 36
  "pkg:npm/rollup@4.5.0"          # 37
  "pkg:npm/babel-core@6.26.3"     # 38
  "pkg:npm/@babel/core@7.23.3"    # 39
  "pkg:npm/@babel/preset-env@7.23.3" # 40

  # 41–50
  "pkg:npm/jest@29.7.0"            # 41
  "pkg:npm/mocha@10.2.0"           # 42
  "pkg:npm/chai@4.3.10"            # 43
  "pkg:npm/sinon@17.0.1"           # 44
  "pkg:npm/supertest@6.3.3"        # 45
  "pkg:npm/nyc@15.1.0"             # 46
  "pkg:npm/cypress@13.6.0"         # 47
  "pkg:npm/playwright@1.40.0"      # 48
  "pkg:npm/puppeteer@21.6.0"       # 49
  "pkg:npm/msw@2.0.8"              # 50

  # 51–100
  "pkg:npm/rxjs@7.8.1"              # 51
  "pkg:npm/immer@10.0.3"            # 52
  "pkg:npm/redux@4.2.1"             # 53
  "pkg:npm/@reduxjs/toolkit@2.0.1"  # 54
  "pkg:npm/react-redux@9.0.4"       # 55
  "pkg:npm/formik@2.4.5"            # 56
  "pkg:npm/yup@1.3.2"               # 57
  "pkg:npm/react-hook-form@7.48.2"  # 58
  "pkg:npm/classnames@2.3.2"        # 59
  "pkg:npm/styled-components@6.1.1" # 60

  "pkg:npm/tailwindcss@3.3.5"       # 61
  "pkg:npm/postcss@8.4.31"          # 62
  "pkg:npm/autoprefixer@10.4.16"    # 63
  "pkg:npm/sass@1.69.5"             # 64
  "pkg:npm/less@4.2.0"              # 65
  "pkg:npm/bulma@0.9.4"             # 66
  "pkg:npm/bootstrap@5.3.2"         # 67
  "pkg:npm/material-ui@4.12.4"      # 68
  "pkg:npm/@mui/material@5.14.18"   # 69
  "pkg:npm/antd@5.11.3"             # 70

  "pkg:npm/three@0.158.0"            # 71
  "pkg:npm/d3@7.8.5"                 # 72
  "pkg:npm/chart.js@4.4.0"           # 73
  "pkg:npm/echarts@5.4.3"            # 74
  "pkg:npm/leaflet@1.9.4"            # 75
  "pkg:npm/mapbox-gl@3.0.1"          # 76
  "pkg:npm/luxon@3.4.4"              # 77
  "pkg:npm/nanoid@5.0.4"             # 78
  "pkg:npm/pino@8.16.1"              # 79
  "pkg:npm/winston@3.11.0"           # 80

  # 81–150
  "pkg:npm/fastify@4.24.3"           # 81
  "pkg:npm/hapi@21.3.2"              # 82
  "pkg:npm/koa@2.14.2"               # 83
  "pkg:npm/nestjs@0.0.1"             # 84
  "pkg:npm/typeorm@0.3.17"           # 85
  "pkg:npm/prisma@5.6.0"             # 86
  "pkg:npm/sequelize@6.35.1"         # 87
  "pkg:npm/pg@8.11.3"                # 88
  "pkg:npm/mysql2@3.6.5"             # 89
  "pkg:npm/sqlite3@5.1.6"            # 90

  "pkg:npm/ioredis@5.3.2"            # 91
  "pkg:npm/redis@4.6.10"             # 92
  "pkg:npm/bull@4.11.4"              # 93
  "pkg:npm/amqplib@0.10.3"           # 94
  "pkg:npm/kafkajs@2.2.4"            # 95
  "pkg:npm/apollo-server@3.13.0"     # 97
  "pkg:npm/@apollo/client@3.8.8"     # 98
  "pkg:npm/urql@4.0.6"               # 99
  "pkg:npm/relay-runtime@16.1.0"     # 100

  # 101–200
  "pkg:npm/next@14.0.3"              # 101
  "pkg:npm/nuxt@3.9.0"               # 102
  "pkg:npm/svelte@4.2.5"             # 103
  "pkg:npm/sveltekit@1.27.6"         # 104
  "pkg:npm/vue@3.3.9"                # 105
  "pkg:npm/vuex@4.1.0"               # 106
  "pkg:npm/pinia@2.1.7"              # 107
  "pkg:npm/astro@4.0.2"              # 108
  "pkg:npm/solid-js@1.8.5"           # 109
  "pkg:npm/qwik@1.3.2"               # 110

  "pkg:npm/esbuild@0.19.8"           # 111
  "pkg:npm/swc@1.3.96"               # 112
  "pkg:npm/faker@5.5.3"              # 113
  "pkg:npm/@faker-js/faker@8.2.0"    # 114
  "pkg:npm/chokidar@3.5.3"           # 115
  "pkg:npm/glob@10.3.10"             # 116
  "pkg:npm/minimist@1.2.8"           # 117
  "pkg:npm/rimraf@5.0.5"             # 118
  "pkg:npm/execa@8.0.1"              # 119
  "pkg:npm/cross-env@7.0.3"          # 120

  "pkg:npm/env-cmd@10.1.0"           # 121
  "pkg:npm/config@3.3.9"             # 122
  "pkg:npm/helmet@7.1.0"             # 123
  "pkg:npm/csurf@1.11.0"             # 124
  "pkg:npm/rate-limiter-flexible@4.0.0" # 125
  "pkg:npm/express-validator@7.0.1"  # 126
  "pkg:npm/passport@0.7.0"           # 127
  "pkg:npm/passport-jwt@4.0.1"       # 128
  "pkg:npm/oauth2-server@3.1.1"      # 129
  "pkg:npm/openid-client@5.6.1"      # 130

  "pkg:npm/swagger-ui-express@5.0.0" # 131
  "pkg:npm/openapi-types@12.1.3"     # 132
  "pkg:npm/yaml@2.3.4"               # 133
  "pkg:npm/xml2js@0.6.2"             # 134
  "pkg:npm/jsdom@23.0.1"             # 135
  "pkg:npm/marked@9.1.2"             # 136
  "pkg:npm/highlight.js@11.9.0"      # 137
  "pkg:npm/pdfkit@0.15.0"            # 138
  "pkg:npm/exceljs@4.4.0"            # 139
  "pkg:npm/csv-parser@3.0.0"         # 140

  "pkg:npm/ftp@0.3.10"               # 141
  "pkg:npm/ssh2@1.15.0"              # 142
  "pkg:npm/aws-sdk@2.1492.0"         # 143
  "pkg:npm/@aws-sdk/client-s3@3.470.0" # 144
  "pkg:npm/googleapis@128.0.0"       # 145
  "pkg:npm/firebase@10.7.0"          # 146
  "pkg:npm/supabase@2.38.2"          # 147
  "pkg:npm/stripe@14.5.0"            # 148
  "pkg:npm/paypal-rest-sdk@1.8.1"    # 149
  "pkg:npm/braintree@3.21.0"         # 150

  "pkg:npm/uuidv7@0.6.3"              # 151
  "pkg:npm/cron@3.1.6"                # 152
  "pkg:npm/node-cron@3.0.3"           # 153
  "pkg:npm/agenda@5.0.0"              # 154
  "pkg:npm/bree@9.2.2"                # 155
  "pkg:npm/pm2@5.3.0"                 # 156
  "pkg:npm/forever@4.0.3"             # 157
  "pkg:npm/cluster@0.7.7"             # 158
  "pkg:npm/graceful-fs@4.2.11"        # 159
  "pkg:npm/mkdirp@3.0.1"              # 160

  "pkg:npm/tslib@2.6.2"               # 161
  "pkg:npm/core-js@3.34.0"            # 162
  "pkg:npm/regenerator-runtime@0.14.1" # 163
  "pkg:npm/whatwg-fetch@3.6.20"       # 164
  "pkg:npm/isomorphic-fetch@3.0.0"    # 165
  "pkg:npm/url@0.11.3"                # 166
  "pkg:npm/querystring@0.2.1"         # 167
  "pkg:npm/buffer@6.0.3"              # 168
  "pkg:npm/events@3.3.0"              # 169
  "pkg:npm/util@0.12.5"               # 170

  "pkg:npm/assert@2.1.0"              # 171
  "pkg:npm/stream-browserify@3.0.0"   # 172
  "pkg:npm/path-browserify@1.0.1"     # 173
  "pkg:npm/os-browserify@0.3.0"       # 174
  "pkg:npm/https-browserify@1.0.0"    # 175
  "pkg:npm/timers-browserify@2.0.12"  # 176
  "pkg:npm/process@0.11.10"           # 177
  "pkg:npm/crypto-js@4.2.0"            # 178
  "pkg:npm/js-cookie@3.0.5"           # 179
  "pkg:npm/localforage@1.10.0"        # 180

  "pkg:npm/idb@8.0.0"                 # 181
  "pkg:npm/workbox-core@7.0.0"        # 182
  "pkg:npm/workbox-precaching@7.0.0"  # 183
  "pkg:npm/serviceworker-webpack-plugin@1.0.1" # 184
  "pkg:npm/pwa-asset-generator@6.3.0" # 185
  "pkg:npm/web-vitals@4.2.4"          # 186
  "pkg:npm/lighthouse@11.3.0"         # 187
  "pkg:npm/axe-core@4.8.2"            # 188
  "pkg:npm/storybook@7.6.6"           # 189
  "pkg:npm/@storybook/react@7.6.6"    # 190

  "pkg:npm/husky@8.0.3"               # 191
  "pkg:npm/lint-staged@15.1.0"        # 192
  "pkg:npm/commitlint@18.4.3"         # 193
  "pkg:npm/semantic-release@22.0.7"   # 194
  "pkg:npm/changesets@2.26.2"         # 195
  "pkg:npm/nx@17.2.8"                 # 196
  "pkg:npm/turborepo@1.11.2"          # 197
  "pkg:npm/lerna@7.4.2"               # 198
  "pkg:npm/rush@5.104.2"              # 199
  "pkg:npm/pnpm@8.10.5"               # 200
)

# Filter packages array if NUM_SAMPLES or range is specified
if [ -n "$RANGE_START" ] && [ -n "$RANGE_END" ]; then
    # Range mode: slice from start to end (end is exclusive, like Python)
    RANGE_LENGTH=$((RANGE_END - RANGE_START))
    TOTAL_COUNT="${#PACKAGES[@]}"
    
    # Validate range bounds
    if [ "$RANGE_START" -ge "$TOTAL_COUNT" ]; then
        echo "Error: Range start ($RANGE_START) is out of bounds (array has $TOTAL_COUNT packages)"
        exit 1
    fi
    if [ "$RANGE_END" -gt "$TOTAL_COUNT" ]; then
        echo "Warning: Range end ($RANGE_END) exceeds array size ($TOTAL_COUNT), using $TOTAL_COUNT instead"
        RANGE_END="$TOTAL_COUNT"
        RANGE_LENGTH=$((RANGE_END - RANGE_START))
    fi
    
    PACKAGES=("${PACKAGES[@]:$RANGE_START:$RANGE_LENGTH}")
    TOTAL_COUNT="${#PACKAGES[@]}"
    echo "Running packages from index $RANGE_START to $((RANGE_END - 1)) ($TOTAL_COUNT package(s))..."
    echo ""
elif [ -n "$NUM_SAMPLES" ]; then
    # Single number mode: first N packages
    PACKAGES=("${PACKAGES[@]:0:$NUM_SAMPLES}")
    TOTAL_COUNT="${#PACKAGES[@]}"
    echo "Running first $TOTAL_COUNT package(s)..."
    echo ""
else
    TOTAL_COUNT="${#PACKAGES[@]}"
    echo "Running all $TOTAL_COUNT packages..."
    echo ""
fi

COUNTER=1
for PURL in "${PACKAGES[@]}"; do
  echo "[$COUNTER/$TOTAL_COUNT] Analyzing $PURL"

  curl -s -X POST "$API_URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"purl\": \"$PURL\"}"

  echo -e "\n-----------------------------------"
  COUNTER=$((COUNTER + 1))
done

echo ""
echo "Completed: $TOTAL_COUNT package(s) processed"