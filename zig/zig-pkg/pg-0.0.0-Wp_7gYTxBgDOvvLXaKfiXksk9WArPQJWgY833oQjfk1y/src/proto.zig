pub const AuthenticationRequest = @import("proto/authentication_request.zig").AuthenticationRequest;
pub const AuthenticationSASLContinue = @import("proto/AuthenticationSASLContinue.zig");
pub const AuthenticationSASLFinal = @import("proto/AuthenticationSASLFinal.zig");
pub const CommandComplete = @import("proto/CommandComplete.zig");
pub const Describe = @import("proto/Describe.zig");
pub const Error = @import("proto/Error.zig");
pub const Execute = @import("proto/Execute.zig");
pub const NotificationResponse = @import("proto/NotificationResponse.zig");
pub const Parse = @import("proto/Parse.zig");
pub const PasswordMessage = @import("proto/PasswordMessage.zig");
pub const Query = @import("proto/Query.zig");
pub const SASLInitialResponse = @import("proto/SASLInitialResponse.zig");
pub const SASLResponse = @import("proto/SASLResponse.zig");
pub const StartupMessage = @import("proto/StartupMessage.zig");
pub const Sync = @import("proto/Sync.zig");

test {
    @import("std").testing.refAllDecls(@This());
}
