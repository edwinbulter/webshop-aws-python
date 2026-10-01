from dataclasses import dataclass, field


@dataclass(frozen=True)
class Address:
    name: str = ""
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "street": self.street,
            "postal_code": self.postal_code,
            "city": self.city,
            "country": self.country,
        }

    @staticmethod
    def from_dict(data: dict) -> "Address":
        return Address(
            name=data.get("name", ""),
            street=data.get("street", ""),
            postal_code=data.get("postal_code", ""),
            city=data.get("city", ""),
            country=data.get("country", ""),
        )


@dataclass(frozen=True)
class UserProfile:
    sub: str
    email: str
    given_name: str = ""
    family_name: str = ""
    shipping_address: Address = field(default_factory=Address)
    billing_address: Address = field(default_factory=Address)

    def to_item(self) -> dict:
        return {
            "PK": f"USER#{self.sub}",
            "SK": "PROFILE",
            "sub": self.sub,
            "email": self.email,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "shipping_address": self.shipping_address.to_dict(),
            "billing_address": self.billing_address.to_dict(),
        }

    @staticmethod
    def from_item(item: dict) -> "UserProfile":
        return UserProfile(
            sub=item["sub"],
            email=item["email"],
            given_name=item.get("given_name", ""),
            family_name=item.get("family_name", ""),
            shipping_address=Address.from_dict(item.get("shipping_address", {})),
            billing_address=Address.from_dict(item.get("billing_address", {})),
        )
