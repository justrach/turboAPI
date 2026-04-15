// Root module that exports all validator functionality
// This is the main entry point for the dhi validation library

pub const validator = @import("validator");
pub const combinators = @import("combinators");
pub const json_validator = @import("json_validator");

// Re-export commonly used types for convenience
pub const ValidationError = validator.ValidationError;
pub const ValidationErrors = validator.ValidationErrors;
pub const ValidationResult = validator.ValidationResult;

pub const BoundedInt = validator.BoundedInt;
pub const BoundedString = validator.BoundedString;
pub const Email = validator.Email;
pub const Pattern = validator.Pattern;

pub const Optional = combinators.Optional;
pub const Default = combinators.Default;
pub const OneOf = combinators.OneOf;
pub const Range = combinators.Range;
pub const Transform = combinators.Transform;

pub const parseAndValidate = json_validator.parseAndValidate;
pub const batchValidate = json_validator.batchValidate;
pub const streamValidate = json_validator.streamValidate;

pub const validateStruct = validator.validateStruct;
pub const deriveValidator = validator.deriveValidator;

test {
    @import("std").testing.refAllDecls(@This());
}
