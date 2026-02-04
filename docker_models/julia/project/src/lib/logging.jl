using Logging


struct StdoutStderrLogger <: AbstractLogger
    min_level::LogLevel
end


Logging.min_enabled_level(logger::StdoutStderrLogger) = logger.min_level
Logging.shouldlog(::StdoutStderrLogger, level, _module, group, id) = true


function Logging.handle_message(
    logger::StdoutStderrLogger,
    level,
    message,
    _module,
    group,
    id,
    file,
    line;
    kwargs...
)
    io = level >= Logging.Warn ? stderr : stdout
    println(io, message)
end

function install_logger(; level::LogLevel = Logging.Info)
    global_logger(StdoutStderrLogger(level))
end
