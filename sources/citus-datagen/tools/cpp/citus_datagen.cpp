#include <algorithm>
#include <chrono>
#include <ctime>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct TenantRange {
    std::int64_t start;
    std::int64_t end;
    std::string logical_region;
};

struct Options {
    std::string table;
    std::string region = "eu";
    std::int64_t tenant_start = 1;
    std::int64_t tenant_end = 1000;
    std::vector<TenantRange> tenant_ranges;
    std::string event_id_mode = "local_sequential";
    std::int64_t events_per_tenant = 100;
    std::int64_t users_per_tenant = 50;
    std::int64_t lookback_days = 30;
    std::uint64_t seed = 42;
    std::int64_t progress_every_tenants = 0;
    std::string distribution = "uniform";
    double hot_tenant_pct = 1.0;
    double hot_event_pct = 50.0;
    std::int64_t base_time_unix = 0;
};

void print_usage(std::ostream& out) {
    out << "usage: citus_datagen --table tenants|users|global_users|events [options]\n"
        << "\noptions:\n"
        << "  --region VALUE\n"
        << "  --tenant-start N\n"
        << "  --tenant-end N\n"
        << "  --tenant-ranges START:END:REGION[,START:END:REGION...]\n"
        << "  --event-id-mode local_sequential|tenant_global\n"
        << "  --events-per-tenant N\n"
        << "  --users-per-tenant N  (for --table global_users, controls global users per tenant)\n"
        << "  --lookback-days N\n"
        << "  --seed N\n"
        << "  --progress-every-tenants N\n"
        << "  --distribution uniform|hot_tenants\n"
        << "  --hot-tenant-pct PCT\n"
        << "  --hot-event-pct PCT\n"
        << "  --base-time-unix N\n";
}

[[noreturn]] void usage_error(const std::string& message) {
    std::cerr << "error: " << message << "\n\n";
    print_usage(std::cerr);
    std::exit(2);
}

std::int64_t parse_i64(const std::string& value, const std::string& name) {
    std::size_t pos = 0;
    long long parsed = 0;
    try {
        parsed = std::stoll(value, &pos, 10);
    } catch (const std::exception&) {
        usage_error("invalid integer for " + name + ": " + value);
    }
    if (pos != value.size()) {
        usage_error("invalid integer for " + name + ": " + value);
    }
    return static_cast<std::int64_t>(parsed);
}

std::uint64_t parse_u64(const std::string& value, const std::string& name) {
    std::size_t pos = 0;
    unsigned long long parsed = 0;
    try {
        parsed = std::stoull(value, &pos, 10);
    } catch (const std::exception&) {
        usage_error("invalid unsigned integer for " + name + ": " + value);
    }
    if (pos != value.size()) {
        usage_error("invalid unsigned integer for " + name + ": " + value);
    }
    return static_cast<std::uint64_t>(parsed);
}

double parse_double(const std::string& value, const std::string& name) {
    std::size_t pos = 0;
    double parsed = 0;
    try {
        parsed = std::stod(value, &pos);
    } catch (const std::exception&) {
        usage_error("invalid decimal for " + name + ": " + value);
    }
    if (pos != value.size()) {
        usage_error("invalid decimal for " + name + ": " + value);
    }
    return parsed;
}

std::vector<TenantRange> parse_tenant_ranges(const std::string& value) {
    std::vector<TenantRange> ranges;
    std::stringstream stream(value);
    std::string item;
    while (std::getline(stream, item, ',')) {
        std::stringstream item_stream(item);
        std::string start_text;
        std::string end_text;
        std::string region;
        if (
            !std::getline(item_stream, start_text, ':')
            || !std::getline(item_stream, end_text, ':')
            || !std::getline(item_stream, region)
            || region.empty()
        ) {
            usage_error("invalid --tenant-ranges entry: " + item);
        }
        const std::int64_t start = parse_i64(start_text, "--tenant-ranges");
        const std::int64_t end = parse_i64(end_text, "--tenant-ranges");
        if (start > end) {
            usage_error("tenant range start must be <= end: " + item);
        }
        ranges.push_back({start, end, region});
    }
    if (ranges.empty()) {
        usage_error("--tenant-ranges must contain at least one range");
    }
    return ranges;
}

Options parse_args(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        std::string arg = argv[index];
        auto require_value = [&](const std::string& name) -> std::string {
            if (index + 1 >= argc) {
                usage_error("missing value for " + name);
            }
            return argv[++index];
        };

        if (arg == "--table") {
            options.table = require_value(arg);
        } else if (arg == "--region") {
            options.region = require_value(arg);
        } else if (arg == "--tenant-start") {
            options.tenant_start = parse_i64(require_value(arg), arg);
        } else if (arg == "--tenant-end") {
            options.tenant_end = parse_i64(require_value(arg), arg);
        } else if (arg == "--tenant-ranges") {
            options.tenant_ranges = parse_tenant_ranges(require_value(arg));
        } else if (arg == "--event-id-mode") {
            options.event_id_mode = require_value(arg);
        } else if (arg == "--events-per-tenant") {
            options.events_per_tenant = parse_i64(require_value(arg), arg);
        } else if (arg == "--users-per-tenant") {
            options.users_per_tenant = parse_i64(require_value(arg), arg);
        } else if (arg == "--lookback-days") {
            options.lookback_days = parse_i64(require_value(arg), arg);
        } else if (arg == "--seed") {
            options.seed = parse_u64(require_value(arg), arg);
        } else if (arg == "--progress-every-tenants") {
            options.progress_every_tenants = parse_i64(require_value(arg), arg);
        } else if (arg == "--distribution") {
            options.distribution = require_value(arg);
        } else if (arg == "--hot-tenant-pct") {
            options.hot_tenant_pct = parse_double(require_value(arg), arg);
        } else if (arg == "--hot-event-pct") {
            options.hot_event_pct = parse_double(require_value(arg), arg);
        } else if (arg == "--base-time-unix") {
            options.base_time_unix = parse_i64(require_value(arg), arg);
        } else if (arg == "--help" || arg == "-h") {
            print_usage(std::cout);
            std::exit(0);
        } else {
            usage_error("unknown argument: " + arg);
        }
    }

    if (
        options.table != "tenants"
        && options.table != "users"
        && options.table != "global_users"
        && options.table != "events"
    ) {
        usage_error("--table must be tenants, users, global_users, or events");
    }
    if (options.tenant_start > options.tenant_end) {
        usage_error("--tenant-start must be <= --tenant-end");
    }
    if (options.tenant_ranges.empty()) {
        options.tenant_ranges.push_back(
            {options.tenant_start, options.tenant_end, options.region}
        );
    }
    if (
        options.event_id_mode != "local_sequential"
        && options.event_id_mode != "tenant_global"
    ) {
        usage_error("--event-id-mode must be local_sequential or tenant_global");
    }
    if (options.events_per_tenant < 0) {
        usage_error("--events-per-tenant must be >= 0");
    }
    if (options.users_per_tenant <= 0) {
        usage_error("--users-per-tenant must be > 0");
    }
    if (options.lookback_days < 0) {
        usage_error("--lookback-days must be >= 0");
    }
    if (options.progress_every_tenants < 0) {
        usage_error("--progress-every-tenants must be >= 0");
    }
    if (options.distribution != "uniform" && options.distribution != "hot_tenants") {
        usage_error("--distribution must be uniform or hot_tenants");
    }
    if (options.hot_tenant_pct <= 0.0 || options.hot_tenant_pct > 100.0) {
        usage_error("--hot-tenant-pct must be in (0, 100]");
    }
    if (options.hot_event_pct <= 0.0 || options.hot_event_pct >= 100.0) {
        usage_error("--hot-event-pct must be in (0, 100)");
    }
    return options;
}

std::int64_t tenant_count(const Options& options) {
    std::int64_t total = 0;
    for (const TenantRange& range : options.tenant_ranges) {
        total += range.end - range.start + 1;
    }
    return total;
}

std::uint64_t splitmix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
}

std::uint64_t row_random(const Options& options, std::int64_t tenant_id, std::int64_t event_offset, std::uint64_t salt) {
    std::uint64_t value = options.seed;
    value ^= static_cast<std::uint64_t>(tenant_id) * 0x9e3779b97f4a7c15ULL;
    value ^= static_cast<std::uint64_t>(event_offset) * 0xbf58476d1ce4e5b9ULL;
    value ^= salt * 0x94d049bb133111ebULL;
    return splitmix64(value);
}

std::string format_utc_timestamp(std::int64_t unix_seconds) {
    std::time_t seconds = static_cast<std::time_t>(unix_seconds);
    std::tm tm_value {};
    gmtime_r(&seconds, &tm_value);
    char buffer[32];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &tm_value);
    return buffer;
}

std::int64_t current_unix_seconds() {
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count();
}

std::string tenant_tier(std::int64_t tenant_id) {
    if (tenant_id % 20 == 0) {
        return "enterprise";
    }
    if (tenant_id % 5 == 0) {
        return "pro";
    }
    return "standard";
}

std::string tenant_status(std::int64_t tenant_id) {
    if (tenant_id % 97 == 0) {
        return "suspended";
    }
    if (tenant_id % 31 == 0) {
        return "inactive";
    }
    return "active";
}

std::string user_segment(std::int64_t user_id) {
    switch ((user_id - 1) % 4) {
        case 0:
            return "consumer";
        case 1:
            return "professional";
        case 2:
            return "power";
        default:
            return "trial";
    }
}

std::string user_status(std::int64_t user_id) {
    if (user_id % 53 == 0) {
        return "suspended";
    }
    if (user_id % 17 == 0) {
        return "inactive";
    }
    return "active";
}

void write_tenants(const Options& options) {
    std::int64_t count = 0;
    const std::int64_t total = tenant_count(options);
    const std::int64_t base_time = options.base_time_unix > 0 ? options.base_time_unix : current_unix_seconds();
    const std::string updated_at = format_utc_timestamp(base_time);
    for (const TenantRange& range : options.tenant_ranges) {
        for (std::int64_t tenant_id = range.start; tenant_id <= range.end; ++tenant_id) {
            std::cout << tenant_id << ','
                      << range.logical_region << ','
                      << tenant_tier(tenant_id) << ','
                      << tenant_status(tenant_id) << ','
                      << updated_at << ','
                      << 1 << '\n';
            ++count;
            if (options.progress_every_tenants > 0 && count % options.progress_every_tenants == 0) {
                std::cerr << "Generated tenants " << count << "/" << total << "\n";
            }
        }
    }
}

void write_users(const Options& options) {
    const std::int64_t total_tenants = tenant_count(options);
    const std::int64_t total_users = total_tenants * options.users_per_tenant;
    const std::int64_t base_time = options.base_time_unix > 0 ? options.base_time_unix : current_unix_seconds();
    const std::string updated_at = format_utc_timestamp(base_time);
    const std::int64_t signup_window_days = std::max<std::int64_t>(1, options.lookback_days * 12 + 1);
    std::int64_t written = 0;

    std::int64_t completed_tenants = 0;
    for (const TenantRange& range : options.tenant_ranges) {
        for (std::int64_t tenant_id = range.start; tenant_id <= range.end; ++tenant_id) {
            for (std::int64_t user_id = 1; user_id <= options.users_per_tenant; ++user_id) {
            const std::int64_t signup_age_days =
                (tenant_id * 17 + user_id * 31 + static_cast<std::int64_t>(options.seed)) % signup_window_days;
            const std::int64_t signup_at = base_time - (signup_age_days * 86400);
            std::cout << tenant_id << ','
                      << user_id << ','
                      << user_segment(user_id) << ','
                      << user_status(user_id) << ','
                      << format_utc_timestamp(signup_at) << ','
                      << updated_at << '\n';
                ++written;
            }
            ++completed_tenants;

            if (options.progress_every_tenants > 0 && completed_tenants % options.progress_every_tenants == 0) {
                std::cerr << "Generated users tenants=" << completed_tenants << "/" << total_tenants
                          << " users=" << written << "/" << total_users << "\n";
            }
        }
    }
}

void write_global_users(const Options& options) {
    const std::int64_t total_tenants = tenant_count(options);
    const std::int64_t total_users = total_tenants * options.users_per_tenant;
    const std::int64_t base_time = options.base_time_unix > 0 ? options.base_time_unix : current_unix_seconds();
    const std::string updated_at = format_utc_timestamp(base_time);
    const std::int64_t signup_window_days = std::max<std::int64_t>(1, options.lookback_days * 12 + 1);
    std::int64_t written = 0;

    std::int64_t completed_tenants = 0;
    for (const TenantRange& range : options.tenant_ranges) {
        for (std::int64_t tenant_id = range.start; tenant_id <= range.end; ++tenant_id) {
            for (std::int64_t user_id = 1; user_id <= options.users_per_tenant; ++user_id) {
            const std::int64_t signup_age_days =
                (tenant_id * 17 + user_id * 31 + static_cast<std::int64_t>(options.seed)) % signup_window_days;
            const std::int64_t signup_at = base_time - (signup_age_days * 86400);
            std::cout << tenant_id << ','
                      << user_id << ','
                      << user_segment(user_id) << ','
                      << user_status(user_id) << ','
                      << range.logical_region << ','
                      << format_utc_timestamp(signup_at) << ','
                      << updated_at << '\n';
                ++written;
            }
            ++completed_tenants;

            if (options.progress_every_tenants > 0 && completed_tenants % options.progress_every_tenants == 0) {
                std::cerr << "Generated global_users tenants=" << completed_tenants << "/" << total_tenants
                          << " global_users=" << written << "/" << total_users << "\n";
            }
        }
    }
}

std::int64_t events_for_tenant(const Options& options, std::int64_t tenant_index, std::int64_t tenant_count) {
    if (options.distribution == "uniform") {
        return options.events_per_tenant;
    }

    const std::int64_t total_events = tenant_count * options.events_per_tenant;
    std::int64_t hot_count = static_cast<std::int64_t>((tenant_count * options.hot_tenant_pct / 100.0) + 0.5);
    hot_count = std::max<std::int64_t>(1, std::min(hot_count, tenant_count));
    const std::int64_t cold_count = tenant_count - hot_count;

    const std::int64_t hot_events = static_cast<std::int64_t>((total_events * options.hot_event_pct / 100.0) + 0.5);
    const std::int64_t cold_events = total_events - hot_events;

    if (tenant_index < hot_count) {
        const std::int64_t base = hot_events / hot_count;
        const std::int64_t remainder = hot_events % hot_count;
        return base + (tenant_index < remainder ? 1 : 0);
    }
    if (cold_count == 0) {
        return 0;
    }
    const std::int64_t cold_index = tenant_index - hot_count;
    const std::int64_t base = cold_events / cold_count;
    const std::int64_t remainder = cold_events % cold_count;
    return base + (cold_index < remainder ? 1 : 0);
}

void write_events(const Options& options) {
    constexpr std::int64_t tenant_event_stride = 1000000;
    const std::int64_t total_tenants = tenant_count(options);
    const std::int64_t total_events = total_tenants * options.events_per_tenant;
    const std::int64_t base_time = options.base_time_unix > 0 ? options.base_time_unix : current_unix_seconds();
    std::int64_t written = 0;

    std::cout << std::fixed << std::setprecision(2);
    std::int64_t tenant_index = 0;
    for (const TenantRange& range : options.tenant_ranges) {
        for (std::int64_t tenant_id = range.start; tenant_id <= range.end; ++tenant_id, ++tenant_index) {
            const std::int64_t tenant_events = events_for_tenant(options, tenant_index, total_tenants);
            if (options.event_id_mode == "tenant_global" && tenant_events >= tenant_event_stride) {
                throw std::runtime_error("tenant_global event IDs support fewer than 1,000,000 events per tenant");
            }
            for (std::int64_t event_offset = 1; event_offset <= tenant_events; ++event_offset) {
                const std::int64_t event_id = options.event_id_mode == "tenant_global"
                    ? tenant_id * tenant_event_stride + event_offset
                    : written + 1;
            const std::int64_t user_id = static_cast<std::int64_t>(
                row_random(options, tenant_id, event_offset, 1) % static_cast<std::uint64_t>(options.users_per_tenant)
            ) + 1;
            const double value = 1.0 + static_cast<double>(
                row_random(options, tenant_id, event_offset, 2) % 99901ULL
            ) / 100.0;
            const std::int64_t age_days = static_cast<std::int64_t>(
                row_random(options, tenant_id, event_offset, 3) % static_cast<std::uint64_t>(options.lookback_days + 1)
            );
            const std::int64_t age_seconds = static_cast<std::int64_t>(
                row_random(options, tenant_id, event_offset, 4) % 86400ULL
            );
            const std::int64_t created_at = base_time - (age_days * 86400) - age_seconds;

            std::cout << event_id << ','
                      << tenant_id << ','
                      << user_id << ','
                      << value << ','
                      << format_utc_timestamp(created_at) << '\n';
                ++written;
            }

            if (options.progress_every_tenants > 0 && (tenant_index + 1) % options.progress_every_tenants == 0) {
                std::cerr << "Generated events tenants=" << (tenant_index + 1) << "/" << total_tenants
                          << " events=" << written << "/" << total_events << "\n";
            }
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);
        std::ios::sync_with_stdio(false);

        if (options.table == "tenants") {
            write_tenants(options);
        } else if (options.table == "users") {
            write_users(options);
        } else if (options.table == "global_users") {
            write_global_users(options);
        } else {
            write_events(options);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << "\n";
        return 1;
    }
}
