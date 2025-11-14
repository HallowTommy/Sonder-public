from django.urls import path
from .views import (
    HomeView, catalog, product_detail, checkout,
    cart_add, cart_update, about, contact, delivery,
    cart_summary, search_products, checkout_submit,
)

app_name = "shop"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("catalog/", catalog, name="catalog"),
    path("product/<slug:slug>/", product_detail, name="product-detail"),
    path("checkout/", checkout, name="checkout"),
    path("cart/add/", cart_add, name="cart_add"),
    path("cart/update/", cart_update, name="cart_update"),
    path("checkout/submit/", checkout_submit, name="checkout_submit"),
    path("about/", about, name="about"),
    path("contact/", contact, name="contact"),
    path("delivery/", delivery, name="delivery"),
    path("api/cart/summary/", cart_summary, name="cart_summary"),
    path("api/search/", search_products, name="search_api"),
]
